"""
The job store - backed by Postgres (via Supabase) instead of an in-memory
dict, so job state survives server restarts and is scoped to whichever user
created each job. See supabase_schema.sql for the table this reads/writes,
and backend/auth.py for how a request gets resolved to a user_id.

Each job still gets its own jobs/<job_id>/ folder on disk for the pipeline's
actual outputs (vod, matches.csv, events.json, ...) - that part is unchanged
from the original design (still the trick that lets us wrap scripts that
hardcode filenames like "events.json" without editing them, since every job
runs in its own working directory). Only the *metadata* (status, step,
owner, cost estimate, ...) moved from the in-memory dict + job.json-per-folder
snapshot into a real table, which is what makes a job survive a restart and
what makes "whose job is this" an actual enforced question instead of
"whoever's running the server can see everything."

Every function here takes a user_id and filters by it - the Supabase client
in auth.py uses the service_role key, which BYPASSES Row Level Security, so
this application-level filtering is the real enforcement (RLS in
supabase_schema.sql is defense-in-depth for if anything ever queries
Supabase directly from the frontend instead of through this backend).

LOCAL DEV MODE: if Supabase isn't configured (see auth.configured()), every
function below falls back to an in-memory dict scoped to auth.LOCAL_USER
instead of touching Postgres at all - this is what lets you run the app with
zero cloud setup (exactly like before accounts existed) and still have the
same functions work once real credentials are added later. `_local_discover()`
mirrors the original jobs.py's folder auto-discovery so a hand-seeded
jobs/demo/ folder (see seed_demo_job.py) shows up immediately either way.
"""

import csv
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from . import audit, pipeline
from .auth import LOCAL_USER, configured, get_service_client

BASE_DIR = Path(__file__).resolve().parent.parent   # poc-starter/
JOBS_DIR = BASE_DIR / "jobs"
JOBS_DIR.mkdir(exist_ok=True)

TABLE = "jobs"

# ---- local dev mode (no Supabase configured) -------------------------------
_LOCAL_JOBS: dict = {}
_local_discovered = False


def _local_discover():
    """Pick up any jobs/<id>/ folder that already has events.json (e.g.
    hand-seeded via seed_demo_job.py) so it's visible immediately without a
    real Supabase project - mirrors what the pre-accounts jobs.py did."""
    global _local_discovered
    if _local_discovered:
        return
    _local_discovered = True
    if not JOBS_DIR.exists():
        return
    for d in sorted(JOBS_DIR.iterdir()):
        if not d.is_dir() or d.name in _LOCAL_JOBS:
            continue
        if (d / "events.json").exists():
            _LOCAL_JOBS[d.name] = {
                "job_id": d.name, "dir": str(d), "status": "done", "step": "done",
                "step_index": pipeline.TOTAL_STEPS, "total_steps": pipeline.TOTAL_STEPS,
                "game": "pokemon", "mode": "doubles", "regulation": "m-b", "source_type": "seed", "url": None,
                "video": None, "matches_found": None, "cost_estimate_usd": None,
                "error": None, "created_at": d.stat().st_mtime, "user_id": LOCAL_USER["id"],
            }
# -----------------------------------------------------------------------------


def _row_to_job(row: dict) -> dict:
    """DB row -> the same dict shape the rest of the backend already expects
    (this used to just be the in-memory dict, verbatim)."""
    return {
        "job_id": row["job_id"], "dir": row["dir"], "status": row["status"],
        "step": row["step"], "step_index": row["step_index"], "total_steps": row["total_steps"],
        "game": row["game"], "mode": row["mode"], "regulation": row.get("regulation", "m-b"),
        "source_type": row.get("source_type"),
        "url": row.get("url"), "video": row.get("video"), "player": row.get("player"),
        "matches_found": row.get("matches_found"), "cost_estimate_usd": row.get("cost_estimate_usd"),
        "error": row.get("error"), "created_at": row.get("created_at"),
        "user_id": row["user_id"],
    }


def create_job(user_id: str, game: str, mode: str, source_type: str,
               regulation: str = "m-b", url: Optional[str] = None,
               player: Optional[str] = None) -> dict:
    """player: only meaningful for source_type="showdown" - which side of the
    replay is "you" (a Showdown username or "p1"/"p2"). None for video jobs.

    regulation: which Pokemon Champions regulation's roster/legal-mechanics
    data to enforce (adapters/pokemon/regulations/<id>.json) - defaults to
    "m-b" (current). See ARCHITECTURE_HANDOFF.md section 3a."""
    job_id = uuid.uuid4().hex[:12]
    d = JOBS_DIR / job_id
    d.mkdir(parents=True, exist_ok=True)

    row = {
        "job_id": job_id, "user_id": user_id, "dir": str(d),
        "status": "queued", "step": "queued", "step_index": 0,
        "total_steps": pipeline.total_steps_for(source_type), "game": game, "mode": mode,
        "regulation": regulation, "source_type": source_type, "url": url, "player": player,
        "video": None, "matches_found": None, "cost_estimate_usd": None,
        "error": None, "created_at": time.time(),
    }
    audit.record("job_created", job_id=job_id, user_id=user_id, game=game, mode=mode,
                 regulation=regulation, source_type=source_type, url=url, player=player)

    if not configured():
        _local_discover()
        _LOCAL_JOBS[job_id] = row
        return dict(row)

    # Don't send created_at to Supabase: it's a `timestamptz` column (see
    # supabase_schema.sql) and row["created_at"] is a Python float (time.time()) -
    # Postgres can't parse a raw epoch float as a timestamp string, so sending
    # it raises "invalid input syntax for type timestamp with time zone".
    # Omitting the key lets the column's own `default now()` fill it in
    # instead; the immediate get_job() below re-fetches the real value (as an
    # ISO-8601 string), which is exactly the shape career.py's _created_at_key
    # and coaching.py's _parse_ts already expect from Supabase-backed rows.
    supabase_row = {k: v for k, v in row.items() if k != "created_at"}
    get_service_client().table(TABLE).insert(supabase_row).execute()
    return get_job(job_id, user_id)


def update_job(job_id: str, user_id: Optional[str] = None, **fields) -> Optional[dict]:
    """Update by job_id; passing user_id scopes the update to a row that user
    actually owns. job_id is already globally unique (a UUID hex), so this is
    mostly a belt-and-suspenders check rather than the primary access control -
    the primary control is that you can only ever have gotten this job_id from
    your own create_job()/list_jobs() calls in the first place."""
    if not configured():
        _local_discover()
        job = _LOCAL_JOBS.get(job_id)
        if job is None:
            return None
        job.update(fields)
        return dict(job)

    q = get_service_client().table(TABLE).update(fields).eq("job_id", job_id)
    if user_id is not None:
        q = q.eq("user_id", user_id)
    resp = q.execute()
    if not resp.data:
        return None
    return _row_to_job(resp.data[0])


def get_job(job_id: str, user_id: str) -> Optional[dict]:
    """Returns None both when the job doesn't exist AND when it belongs to
    someone else - a stranger's job_id should 404 exactly like a made-up one,
    not leak "this exists but isn't yours." (In local dev mode there's only
    ever one user, so this just checks existence.)"""
    if not configured():
        _local_discover()
        job = _LOCAL_JOBS.get(job_id)
        return dict(job) if job else None

    resp = (get_service_client().table(TABLE).select("*")
            .eq("job_id", job_id).eq("user_id", user_id).limit(1).execute())
    if not resp.data:
        return None
    return _row_to_job(resp.data[0])


def list_jobs(user_id: str) -> list[dict]:
    if not configured():
        _local_discover()
        return [dict(j) for j in _LOCAL_JOBS.values()]

    resp = (get_service_client().table(TABLE).select("*")
            .eq("user_id", user_id).order("created_at", desc=True).execute())
    return [_row_to_job(r) for r in resp.data]


def job_dir(job_id: str, user_id: str) -> Optional[Path]:
    job = get_job(job_id, user_id)
    return Path(job["dir"]) if job else None


def _estimate_cost(job_id: str, user_id: str):
    """Very rough $ estimate once matches.csv exists (see ARCHITECTURE_HANDOFF.md
    section 6: cost-tiered runs land around $0.10-0.20/match)."""
    d = job_dir(job_id, user_id)
    if d is None:
        return
    matches_csv = d / "matches.csv"
    if not matches_csv.exists():
        return
    with open(matches_csv, newline="", encoding="utf-8") as f:
        n = sum(1 for _ in csv.DictReader(f))
    update_job(job_id, user_id, matches_found=n, cost_estimate_usd=round(n * 0.15, 2))


def start_job(job_id: str, user_id: str):
    """Kick off the pipeline in a background thread. Returns immediately -
    check progress via GET /jobs/{id}."""

    def _progress(step: str, step_index: int):
        update_job(job_id, user_id, status="running", step=step, step_index=step_index)
        _estimate_cost(job_id, user_id)   # no-op until matches.csv exists, then fills itself in
        audit.record("job_step", job_id=job_id, user_id=user_id, step=step, step_index=step_index)

    def _run():
        job = get_job(job_id, user_id)
        if job is None:
            return
        try:
            if job["source_type"] == "showdown":
                # No video, no Gemini call at all - see backend/pipeline.py's
                # run_showdown_pipeline and showdown_import.py.
                pipeline.run_showdown_pipeline(
                    job_dir=Path(job["dir"]), game=job["game"], mode=job["mode"],
                    player=job.get("player") or "p1", on_progress=_progress,
                    regulation=job.get("regulation") or "m-b",
                )
                update_job(job_id, user_id, status="done", step="done",
                           step_index=pipeline.total_steps_for("showdown"))
            else:
                video_path = pipeline.run_full_pipeline(
                    job_dir=Path(job["dir"]),
                    game=job["game"],
                    mode=job["mode"],
                    source_type=job["source_type"],
                    url=job["url"],
                    on_progress=_progress,
                    regulation=job.get("regulation") or "m-b",
                )
                update_job(job_id, user_id, status="done", step="done",
                           step_index=pipeline.total_steps_for(job["source_type"]), video=video_path)
            audit.record("job_completed", job_id=job_id, user_id=user_id, source_type=job["source_type"])
        except Exception as e:
            update_job(job_id, user_id, status="failed", error=str(e)[:500])
            audit.record("job_failed", job_id=job_id, user_id=user_id,
                         source_type=job.get("source_type"), error=str(e)[:500])

    threading.Thread(target=_run, daemon=True).start()
