"""
Runs the pipeline scripts for one job.

Design choice worth explaining: rather than importing analyze_matches.py etc.
as Python functions and calling them in-process, we shell out to them with
`subprocess.run(..., cwd=job_dir)` - exactly like run_full.py already does.
Why, even though ARCHITECTURE_HANDOFF.md suggests importing:

  - Several scripts (analyze_matches.save_outputs, for one) write to hardcoded
    relative filenames like "events.json". Importing them in-process would mean
    every concurrent job fights over the same file unless we start rewriting
    the scripts to accept explicit output paths. Running each job as a
    subprocess with its OWN working directory gets that isolation for free -
    zero changes needed to the extraction/video scripts.
  - These steps are long-running (minutes to hours) and call an external API
    (Gemini) and FFmpeg. A crash in one job's subprocess can't take down the
    FastAPI server or another job.

The three pure-analytics scripts (battle_record.py, player_report.py,
coach_report.py) WERE renamed and ARE imported directly, in analytics.py -
those only read events.json and do math, no shared-state problem, and
importing them lets us return structured JSON instead of re-parsing the
markdown reports they write.
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

BASE_DIR = Path(__file__).resolve().parent.parent   # poc-starter/
ADAPTERS_DIR = BASE_DIR / "adapters"

STEPS = ["get_video", "compose_schema", "structure_pass", "analyze_matches",
          "battle_record", "player_report", "coach_report", "transcribe"]
TOTAL_STEPS = len(STEPS)

# The Showdown-replay path (see showdown_import.py / ARCHITECTURE_HANDOFF.md
# section 2a) skips every video/AI-specific step - no video to fetch, no
# structure_pass (no video to scan for match boundaries), no analyze_matches
# (no Gemini call at all), no transcribe (no audio track). It still runs
# compose_schema (so the report's `rules` field is populated the same way)
# and the three pure-analytics steps, since those only read events.json and
# don't care which pipeline produced it.
STEPS_SHOWDOWN = ["get_replays", "compose_schema", "battle_record", "player_report", "coach_report"]


def total_steps_for(source_type: str) -> int:
    """Different source types have different step counts (see STEPS vs.
    STEPS_SHOWDOWN above) - jobs.py needs this at job-creation time, before
    the pipeline itself has even started, to populate JobStatus.total_steps
    correctly for a progress bar."""
    return len(STEPS_SHOWDOWN) if source_type == "showdown" else len(STEPS)


class StepFailed(RuntimeError):
    pass


def _run(script: str, args: list[str], cwd: Path, optional: bool = False):
    cmd = [sys.executable, str(BASE_DIR / script)] + args
    # Force UTF-8 on both ends of the pipe. Several scripts print emoji
    # (analyze_matches.py's "🚫 REJECTED illegal species..." lines, for one) -
    # fine when run interactively (Windows' console layer handles Unicode),
    # but when stdout/stderr are redirected to a pipe (as capture_output=True
    # does here), Python falls back to the OS's legacy locale encoding (often
    # cp1252 on Windows) instead of UTF-8. That encoding can't represent an
    # emoji, so the CHILD process itself crashes with an unhandled
    # UnicodeEncodeError the moment it tries to print one - which looks
    # exactly like a normal script failure (exit 1, a truncated traceback)
    # from out here, and was genuinely confusing to track down: the same
    # command run by hand in a real terminal works fine, only breaks when
    # this function's subprocess.run captures its output.
    # PYTHONIOENCODING/PYTHONUTF8 make the child open stdout/stderr as UTF-8
    # regardless of how it's invoked; encoding="utf-8" (with errors="replace"
    # as a last-resort safety net) makes sure we decode what it sends back
    # correctly on this end too.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", env=env)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip()[-1500:]
        if optional:
            return  # e.g. transcribe.py: whisper missing shouldn't fail the job
        raise StepFailed(f"{script} failed (exit {result.returncode}):\n{tail}")


def run_full_pipeline(job_dir: Path, game: str, mode: str, source_type: str,
                       url: Optional[str], on_progress: Callable[[str, int], None],
                       regulation: str = "m-b") -> str:
    """Runs every step for one job. Returns the resolved video path (relative
    to job_dir). Raises StepFailed on the first non-optional failure.

    `regulation` (e.g. "m-b" current, "m-a" launch/superseded - see
    adapters/pokemon/regulations/<id>.json and ARCHITECTURE_HANDOFF.md
    section 3a) is threaded through to BOTH compose_schema.py (so the
    composed schema.json's `rules` carry this regulation's legal_mechanics/
    format_notes) AND analyze_matches.py (so species legality is actually
    enforced against this regulation's roster, not whatever the module's
    hardcoded default happens to be) - the two need to agree, since
    schema.json's rules is what the coaching/report side reads, while
    analyze_matches's own --regulation flag is what the extraction side
    enforces."""

    if not os.environ.get("GEMINI_API_KEY"):
        raise StepFailed("GEMINI_API_KEY is not set in the backend's environment.")

    # step 0: get the video into job_dir
    on_progress("get_video", 0)
    if source_type == "url":
        _run("fetch_vod.py", ["--url", url, "--out", "vod"], cwd=job_dir)
        video = next((f for f in os.listdir(job_dir) if f.startswith("vod.")), None)
        if not video:
            raise StepFailed("fetch_vod.py reported success but no vod.* file was found.")
    else:
        video = next((f for f in os.listdir(job_dir) if f.startswith("vod.")), None)
        if not video:
            raise StepFailed("No uploaded video found in job dir (expected vod.<ext>).")

    # step 1: compose schema.json for this game/mode/regulation (shared adapters/ dir,
    # absolute path since job_dir has no adapters/ folder of its own)
    on_progress("compose_schema", 1)
    _run("compose_schema.py", ["--game", game, "--mode", mode, "--regulation", regulation,
                               "--adapters", str(ADAPTERS_DIR), "--out", "schema.json"], cwd=job_dir)

    # step 2: find every match window -> matches.csv
    on_progress("structure_pass", 2)
    _run("structure_pass.py", ["--video", video, "--out", "matches.csv",
                               "--frames-dir", "structure_frames"], cwd=job_dir)

    # step 3: per-match roster + events + winner -> events.json/events.csv
    on_progress("analyze_matches", 3)
    _run("analyze_matches.py", ["--video", video, "--matches", "matches.csv",
                                "--schema", "schema.json", "--workdir", "match_frames",
                                "--regulation", regulation, "--adapters", str(ADAPTERS_DIR)], cwd=job_dir)

    # steps 4-6: pure-Python analytics, no AI calls
    on_progress("battle_record", 4)
    _run("battle_record.py", ["--events", "events.json", "--out", "battle_record.csv"], cwd=job_dir)

    on_progress("player_report", 5)
    _run("player_report.py", ["--events", "events.json", "--out", "player_report.md"], cwd=job_dir)

    on_progress("coach_report", 6)
    _run("coach_report.py", ["--events", "events.json", "--out", "coach_report.md"], cwd=job_dir)

    # step 7: transcript is optional and non-blocking (matches run_full.py's behavior)
    on_progress("transcribe", 7)
    _run("transcribe.py", ["--video", video, "--matches", "matches.csv", "--model", "small"],
         cwd=job_dir, optional=True)

    # Deliberately NOT cleaning up structure_frames/match_frames anymore -
    # every event in events.json carries a `reference_frame` path (see
    # analyze_matches.attach_reference_frames) pointing INTO match_frames/,
    # which the dashboard uses to show/correct events by eye (GET
    # /jobs/{id}/frame/{path}). Deleting these would silently break every
    # reference photo right after the job finished. This does mean a job's
    # disk footprint stays roughly what it was during processing - see
    # ARCHITECTURE_HANDOFF.md's data-retention note for the tradeoff.

    return video


def run_showdown_pipeline(job_dir: Path, game: str, mode: str, player: str,
                           on_progress: Callable[[str, int], None],
                           regulation: str = "m-b") -> None:
    """Runs the Showdown-replay path for one job (see STEPS_SHOWDOWN above).
    No video, no FFmpeg, no Gemini call anywhere in this function - the
    replay(s) already saved into job_dir (as replay0.<ext>, replay1.<ext>, ...
    by create_job in main.py) or a list of replay URLs (one per line, in
    job_dir/replay_urls.txt) get parsed straight into events.json by
    showdown_import.py, which is a complete, deterministic record of the
    match with zero AI involved - see showdown_import.py's own module
    docstring. Every step after that is identical to the video pipeline
    because events.json's shape is identical either way.

    `regulation` is passed to BOTH showdown_import.py (species-legality
    check - Showdown enforces format legality server-side, so this mostly
    guards against a replay imported under a mismatched regulation label)
    and compose_schema.py (so schema.json's `rules` reflect the chosen
    regulation, same as the video path)."""

    # step 0: parse the replay(s) already sitting in job_dir into events.json
    on_progress("get_replays", 0)
    replay_files = sorted(f for f in os.listdir(job_dir)
                          if f.startswith("replay") and (f.endswith(".html") or f.endswith(".json")))
    urls_path = job_dir / "replay_urls.txt"
    if replay_files:
        _run("showdown_import.py", ["--files", *replay_files, "--player", player,
                                     "--out", "events.json", "--regulation", regulation,
                                     "--adapters", str(ADAPTERS_DIR)], cwd=job_dir)
    elif urls_path.exists():
        urls = [u.strip() for u in urls_path.read_text(encoding="utf-8").splitlines() if u.strip()]
        if not urls:
            raise StepFailed("replay_urls.txt exists but contained no URLs.")
        _run("showdown_import.py", ["--urls", *urls, "--player", player,
                                     "--out", "events.json", "--regulation", regulation,
                                     "--adapters", str(ADAPTERS_DIR)], cwd=job_dir)
    else:
        raise StepFailed("No uploaded replay file(s) or replay URL(s) found in job dir "
                         "(expected replay0.html/.json or replay_urls.txt).")

    # step 1: compose_schema.py isn't needed for extraction here (showdown_import.py
    # doesn't use it at all) but IS still worth running for its `rules` output -
    # GET /jobs/{id}/report reads schema.json's rules field regardless of source_type.
    on_progress("compose_schema", 1)
    _run("compose_schema.py", ["--game", game, "--mode", mode, "--regulation", regulation,
                               "--adapters", str(ADAPTERS_DIR), "--out", "schema.json"], cwd=job_dir)

    # steps 2-4: identical pure-Python analytics scripts the video path uses -
    # they only ever read events.json, so they don't know or care that this
    # job's events.json came from a replay log instead of Gemini.
    on_progress("battle_record", 2)
    _run("battle_record.py", ["--events", "events.json", "--out", "battle_record.csv"], cwd=job_dir)

    on_progress("player_report", 3)
    _run("player_report.py", ["--events", "events.json", "--out", "player_report.md"], cwd=job_dir)

    on_progress("coach_report", 4)
    _run("coach_report.py", ["--events", "events.json", "--out", "coach_report.md"], cwd=job_dir)
