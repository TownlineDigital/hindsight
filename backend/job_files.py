"""
Pure file-handling helpers for job data - deliberately dependency-free (no
fastapi, no supabase) so they're unit-testable without either package
installed, matching this project's established pattern (gemini_batch.py's
pure-logic half, pipeline.py's _run, showdown_import.py's build_sources)
of separating framework glue from logic that can be verified on its own.

backend/main.py imports both of these rather than reimplementing them
inline, so the actual security-relevant path check and the actual file
writes are exercised by tests/test_job_files.py without needing a real
FastAPI app spun up.
"""

import csv
import json
import os
import tempfile
from pathlib import Path


def safe_frame_path(job_root, frame_path: str) -> Path:
    """Resolves `frame_path` against `job_root` and returns the resulting
    absolute Path - or raises ValueError if the result would escape
    job_root (e.g. frame_path="../../etc/passwd" or an absolute path that
    overrides the join entirely). This is the actual security check behind
    GET /jobs/{id}/frame/{path} - a stranger (or a malformed reference_frame
    value) must never be able to read a file outside that one job's own
    folder."""
    job_root = Path(job_root).resolve()
    full = (job_root / frame_path).resolve()
    full.relative_to(job_root)   # raises ValueError if full is not inside job_root
    return full


def _atomic_write(path: Path, write_fn) -> None:
    """Writes a file so it's NEVER left half-written on disk: `write_fn(f)`
    writes into a temp file created in the SAME directory as `path` (same
    filesystem, so the final os.replace() below is a single atomic rename,
    not a cross-device copy), and only once that completes fully without
    raising does the temp file get moved onto the real path. If anything
    interrupts the write - the process crashes, gets killed, the machine
    loses power, whatever - `path` still holds either its old, fully-valid
    content or is untouched; it can never end up holding a half-written,
    corrupted result the way a plain `open(path, "w")` can.

    This exists because of a real corrupted events.json found in production:
    a truncated string value and a duplicated tail fragment, both exactly
    the shape of damage a plain non-atomic write leaves when interrupted
    partway through. See ARCHITECTURE_HANDOFF.md's data-retention section."""
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            write_fn(f)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def save_events(path, events: list) -> None:
    """Writes events.json AND the matching events.csv at an explicit
    absolute `path` - mirrors analyze_matches.save_outputs()/
    showdown_import.save_outputs() exactly, but parameterized by path
    instead of hardcoded relative filenames: those two assume the process's
    cwd IS the job's own folder (true when a pipeline script runs as a
    subprocess with cwd=job_dir - see backend/pipeline.py), which is NOT
    true inside the FastAPI server (its cwd is wherever uvicorn was
    launched from, not any particular job's folder). Both files are written
    atomically (see _atomic_write) so an interruption mid-write can never
    leave a corrupted events.json/events.csv on disk."""
    path = Path(path)
    _atomic_write(path, lambda f: json.dump(events, f, indent=2))
    if events:
        keys = []
        for e in events:
            for k in e.keys():
                if k not in keys:
                    keys.append(k)

        def _write_csv(f):
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for e in events:
                w.writerow(e)

        _atomic_write(path.with_suffix(".csv"), _write_csv)
