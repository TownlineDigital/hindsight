"""
FastAPI app implementing the contract in ARCHITECTURE_HANDOFF.md section 8.

Run it (from poc-starter/):
  py -m pip install -r requirements.txt
  copy .env.example .env   (then fill in real values - see README_BACKEND.md "Accounts")
  py -m uvicorn backend.main:app --reload --port 8000

Then open http://127.0.0.1:8000/docs for interactive API docs (FastAPI builds
this for free from the type hints below).
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent.parent
META_DIR = BASE_DIR / "meta"
STATIC_DIR = Path(__file__).resolve().parent / "static"
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Load poc-starter/.env (GEMINI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
# before anything below reads os.environ - this replaces having to `set`/`export`
# these every session. Real values live only in .env (gitignored); .env.example
# documents what's needed. override=False so a value already set in your actual
# shell environment still wins (useful for CI/deployment).
load_dotenv(BASE_DIR / ".env", override=False)

from . import analytics, api_keys, audit, auth, career, coaching, event_corrections, job_files, jobs   # noqa: E402  (after load_dotenv - jobs.py needs SUPABASE_* at import time)
from .models import (   # noqa: E402
    ApiKeyCreate, ClientEvent, CoachAnswer, CoachQuestion, EventCorrection, JobStatus,
    NoteCreate, NoteUpdate, RedeemShareLink, RenameStudent, ShareLinkCreate,
)

app = FastAPI(title="VGC Coach API", version="0.1.0")

# Wide open for local dev so a separately-hosted frontend can call this from
# any port too. Tighten this before deploying anywhere real.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# The React dashboard (frontend/, built into here - see backend/README_BACKEND.md
# "Frontend"), mounted at /dashboard via FastAPI's StaticFiles.
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/dashboard", StaticFiles(directory=str(STATIC_DIR), html=True), name="dashboard")


def _job_or_404(job_id: str, user: dict) -> dict:
    """Every /jobs/{id}/... route needs this - looks up the job AND checks
    ownership in one place. jobs.get_job() already returns None for both
    "doesn't exist" and "exists but isn't yours" (see backend/jobs.py), so a
    stranger's job_id 404s exactly like a made-up one - it never reveals
    which is which."""
    job = jobs.get_job(job_id, user["id"])
    if not job:
        raise HTTPException(404, f"No job '{job_id}'")
    return job


@app.get("/auth/status")
def auth_status():
    """Tells the frontend whether real accounts are required. When Supabase
    isn't configured yet (no .env filled in), the frontend skips the sign-in
    screen entirely and every request is treated as one fixed local user (see
    backend/auth.py's LOCAL_USER) - this is what lets you run the app and
    check the dashboard with zero cloud setup."""
    return {"accounts_required": auth.configured()}


def _read_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- jobs -----
# Every endpoint below takes `user: dict = Depends(auth.current_user)` - that
# dependency reads the `Authorization: Bearer <token>` header the frontend
# attaches after a Supabase sign-in (see frontend/src/lib/supabase.js) and
# resolves it to a real user, or raises 401 if there's no valid session. See
# backend/auth.py for the full explanation.

@app.post("/jobs", response_model=JobStatus)
async def create_job(
    source_type: str = Form(..., description="'url' (video URL) | 'upload' (video file) | "
                             "'showdown' (Pokemon Showdown replay(s), see 'files'/'urls'/'player' below)"),
    game: str = Form("pokemon"),
    mode: str = Form("doubles", description="'doubles' or 'singles' - see adapters/pokemon/{doubles,"
                     "singles}.json"),
    regulation: str = Form("m-b", description="Which Pokemon Champions regulation's roster/legal-"
                            "mechanics data to enforce - 'm-b' (current) or 'm-a' (launch, superseded "
                            "2026-06-17). See adapters/pokemon/regulations/<id>.json and "
                            "ARCHITECTURE_HANDOFF.md section 3a."),
    url: Optional[str] = Form(None, description="video URL, only for source_type='url'"),
    file: Optional[UploadFile] = File(None, description="video file, only for source_type='upload'"),
    files: Optional[List[UploadFile]] = File(
        None, description="one or more saved Showdown replay .html/.json files - only for "
        "source_type='showdown'. Combined into one job as consecutive matches, same as "
        "showdown_import.py's --files."),
    urls: Optional[List[str]] = Form(
        None, description="one or more live Showdown replay URLs (replay.pokemonshowdown.com/...) - "
        "only for source_type='showdown', as an alternative to uploading files. Combined into one "
        "job as consecutive matches, same as showdown_import.py's --urls."),
    player: str = Form("p1", description="which side is 'you' in a Showdown replay - a Showdown "
                       "username (case-insensitive) or 'p1'/'p2'. Only meaningful for "
                       "source_type='showdown'; a replay has no built-in notion of 'the player' the "
                       "way a video of your own POV does."),
    name: Optional[str] = Form(None, description="User-given label for this upload, shown in the "
                               "frontend's Gameplay dropdown instead of the raw job_id. Optional - a "
                               "blank/omitted value gets an auto-generated fallback (see "
                               "backend/jobs._default_job_name)."),
    user: dict = Depends(auth.current_user),
):
    if source_type not in ("url", "upload", "showdown"):
        raise HTTPException(400, "source_type must be 'url', 'upload', or 'showdown'")
    if source_type == "url" and not url:
        raise HTTPException(400, "url is required when source_type='url'")
    if source_type == "upload" and not file:
        raise HTTPException(400, "file is required when source_type='upload'")
    if source_type == "showdown" and not files and not urls:
        raise HTTPException(400, "at least one of 'files' or 'urls' is required when source_type='showdown'")
    if source_type == "showdown" and files and urls:
        raise HTTPException(400, "pass either 'files' or 'urls' for source_type='showdown', not both "
                                  "(mirrors showdown_import.py's mutually-exclusive CLI options)")

    job = jobs.create_job(user_id=user["id"], game=game, mode=mode, source_type=source_type,
                          regulation=regulation, url=url,
                          player=player if source_type == "showdown" else None, name=name)

    if source_type == "upload":
        ext = Path(file.filename or "vod.mp4").suffix or ".mp4"
        dest = Path(job["dir"]) / f"vod{ext}"
        # stream to disk in chunks - these files can be many GB, never load whole thing in memory
        with open(dest, "wb") as out:
            shutil.copyfileobj(file.file, out, length=1024 * 1024)
        await file.close()

    elif source_type == "showdown":
        if files:
            # replay0.html, replay1.json, ... - run_showdown_pipeline (backend/pipeline.py)
            # looks for exactly this "replay<N>.<ext>" naming to find them again.
            for i, f in enumerate(files):
                ext = Path(f.filename or f"replay{i}.html").suffix or ".html"
                dest = Path(job["dir"]) / f"replay{i}{ext}"
                with open(dest, "wb") as out:
                    shutil.copyfileobj(f.file, out, length=1024 * 1024)
                await f.close()
        else:
            # replay_urls.txt, one URL per line - run_showdown_pipeline reads this back
            # when no uploaded replay files are present in the job dir.
            urls_path = Path(job["dir"]) / "replay_urls.txt"
            urls_path.write_text("\n".join(u.strip() for u in urls if u.strip()), encoding="utf-8")

    jobs.start_job(job["job_id"], user["id"])
    return JobStatus(job_id=job["job_id"], status="queued", step="queued", step_index=0,
                     total_steps=job["total_steps"], game=game, mode=mode, regulation=regulation,
                     source_type=source_type, name=job["name"])


@app.get("/jobs")
def list_jobs(user: dict = Depends(auth.current_user)):
    return jobs.list_jobs(user["id"])


@app.get("/jobs/{job_id}", response_model=JobStatus)
def job_status(job_id: str, user: dict = Depends(auth.current_user)):
    job = _job_or_404(job_id, user)
    return JobStatus(
        job_id=job["job_id"], status=job["status"], step=job["step"],
        step_index=job["step_index"], total_steps=job["total_steps"],
        matches_found=job.get("matches_found"), cost_estimate_usd=job.get("cost_estimate_usd"),
        error=job.get("error"), video=job.get("video"), game=job["game"], mode=job["mode"],
        regulation=job.get("regulation"), source_type=job.get("source_type"),
        name=job.get("name"),
    )


@app.get("/jobs/{job_id}/matches")
def job_matches(job_id: str, user: dict = Depends(auth.current_user)):
    job = _job_or_404(job_id, user)
    path = Path(job["dir"]) / "matches.csv"
    if not path.exists():
        raise HTTPException(409, f"matches.csv not ready yet (job status: {job['status']}, step: {job['step']})")
    import csv
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@app.get("/jobs/{job_id}/events")
def job_events(job_id: str, user: dict = Depends(auth.current_user)):
    job = _job_or_404(job_id, user)
    path = Path(job["dir"]) / "events.json"
    if not path.exists():
        raise HTTPException(409, f"events.json not ready yet (job status: {job['status']}, step: {job['step']})")
    return _read_json(path)


@app.get("/jobs/{job_id}/frame/{frame_path:path}")
def job_frame(job_id: str, frame_path: str, user: dict = Depends(auth.current_user)):
    """Serves one stored reference image - e.g. the path in an event's
    `reference_frame` field (see analyze_matches.attach_reference_frames) -
    so the dashboard can show what the AI was actually looking at. Frames
    are never deleted after a job finishes (see backend/pipeline.py's
    data-retention note), so this works for any job regardless of age.

    Deliberately a dedicated endpoint rather than mounting the job folder as
    static files: this way the SAME ownership check every other /jobs/{id}/...
    route uses (_job_or_404) applies here too - a stranger can't fetch your
    frames just by guessing a job_id/path, the way a bare static mount
    would allow."""
    job = _job_or_404(job_id, user)
    try:
        full = job_files.safe_frame_path(job["dir"], frame_path)
    except ValueError:
        raise HTTPException(400, "Invalid frame path.")
    if not full.is_file():
        raise HTTPException(404, f"No such frame: {frame_path}")
    return FileResponse(full)


@app.get("/jobs/{job_id}/latest-frame")
def job_latest_frame(job_id: str, user: dict = Depends(auth.current_user)):
    """Lightweight polling endpoint for the "New Gameplay" loading screen's
    live frame preview (added 2026-07-09, direct user request: "previews the
    frames being analyzed as it loads"). Returns the SAME relative-path shape
    GET /jobs/{id}/frame/{path} expects (so the frontend can reuse
    api.frameBlobUrl unmodified), for whichever frame was most recently
    written to disk by structure_pass.py/analyze_matches.py - see
    job_files.latest_frame_path's own docstring for why polling "what's
    newest on disk" is the mechanism, rather than a real progress callback.

    `{"path": null}` (never a 404) when nothing's been written yet - still
    being in get_video/compose_schema with no frame sampled yet is a normal
    early-job state, not an error; the frontend just shows no preview yet."""
    job = _job_or_404(job_id, user)
    return {"path": job_files.latest_frame_path(job["dir"])}


@app.patch("/jobs/{job_id}/events/{index}")
def correct_event(job_id: str, index: int, body: EventCorrection, user: dict = Depends(auth.current_user)):
    """Lets a user fix a wrong AI call by hand - e.g. {"fields": {"pokemon":
    "Charizard"}} to correct a misread species on one event. Only the keys
    given in `fields` are overwritten; everything else about the event
    (including its `reference_frame`, if any) is left as-is. The correction
    itself is recorded to the internal audit log (backend/audit.py), not
    just silently applied - see ARCHITECTURE_HANDOFF.md's data-retention note.

    If `fields` corrects `pokemon`, the SAME wrong name is also fixed on
    every other event in this match that shares this event's side (actor) -
    see backend/event_corrections.py for why a single misread almost always
    recurs across many events, and this is what actually addresses "I fixed
    one event and nothing else changed" (a roster is fixed for the whole
    match, so the old wrong name was wrong everywhere it appears for that
    side, not just at this one index). The response's `cascaded_indices`
    lists every OTHER event index this also touched."""
    job = _job_or_404(job_id, user)
    path = Path(job["dir"]) / "events.json"
    if not path.exists():
        raise HTTPException(409, f"events.json not ready yet (job status: {job['status']}, step: {job['step']})")

    events = _read_json(path)
    if index < 0 or index >= len(events):
        raise HTTPException(404, f"No event at index {index} (this job has {len(events)} events).")

    before = dict(events[index])
    events[index].update(body.fields)
    events[index]["corrected"] = True
    events[index]["corrected_at"] = time.time()
    events[index]["corrected_by"] = user["id"]

    cascaded_indices = []
    new_pokemon = body.fields.get("pokemon")
    old_pokemon = before.get("pokemon")
    if new_pokemon and old_pokemon and new_pokemon != old_pokemon:
        cascaded_indices = event_corrections.cascade_pokemon_correction(
            events, before.get("match"), before.get("actor"), old_pokemon, new_pokemon)
        now = time.time()
        for i in cascaded_indices:
            events[i]["corrected_at"] = now
            events[i]["corrected_by"] = user["id"]

    job_files.save_events(path, events)
    audit.record("event_corrected", job_id=job_id, user_id=user["id"], index=index,
                 before=before, after=dict(events[index]), cascaded_indices=cascaded_indices)
    result = dict(events[index])
    result["cascaded_indices"] = cascaded_indices
    return result


@app.get("/jobs/{job_id}/record")
def job_record(job_id: str, user: dict = Depends(auth.current_user)):
    job = _job_or_404(job_id, user)
    path = Path(job["dir"]) / "events.json"
    if not path.exists():
        raise HTTPException(409, f"events.json not ready yet (job status: {job['status']}, step: {job['step']})")
    return analytics.compute_record(_read_json(path))


@app.get("/jobs/{job_id}/report")
def job_report(job_id: str, user: dict = Depends(auth.current_user)):
    job = _job_or_404(job_id, user)
    d = Path(job["dir"])
    path = d / "events.json"
    if not path.exists():
        raise HTTPException(409, f"events.json not ready yet (job status: {job['status']}, step: {job['step']})")
    rules = None
    schema_path = d / "schema.json"
    if schema_path.exists():
        rules = _read_json(schema_path).get("rules")
    return analytics.compute_report(_read_json(path), rules=rules)


@app.get("/jobs/{job_id}/matches/summary")
def job_matches_summary(job_id: str, user: dict = Depends(auth.current_user)):
    """Not in the original section-8 contract - GET /jobs/{id}/matches already
    covers matches.csv verbatim. This is what the dashboard actually shows,
    since raw start/end timestamps aren't useful on their own: result, lead,
    brought, and duration, per match."""
    job = _job_or_404(job_id, user)
    d = Path(job["dir"])
    events_path = d / "events.json"
    if not events_path.exists():
        raise HTTPException(409, f"events.json not ready yet (job status: {job['status']}, step: {job['step']})")
    rows = analytics.compute_match_list(_read_json(events_path))

    durations = {}
    matches_csv = d / "matches.csv"
    if matches_csv.exists():
        import csv
        with open(matches_csv, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    durations[int(r["match"])] = float(r["duration_seconds"])
                except (KeyError, ValueError):
                    pass
    for row in rows:
        row["duration_seconds"] = durations.get(row["match"])
    return rows


@app.get("/jobs/{job_id}/skill-scores")
def job_skill_scores(job_id: str, user: dict = Depends(auth.current_user)):
    """The 4 progression scores (tempo/adaptability/execution/closing) + confidence
    tier - see skill_scores.py. Written but never wired into the API until now
    (ARCHITECTURE_HANDOFF.md section 4 already documents this as dashboard-facing)."""
    job = _job_or_404(job_id, user)
    path = Path(job["dir"]) / "events.json"
    if not path.exists():
        raise HTTPException(409, f"events.json not ready yet (job status: {job['status']}, step: {job['step']})")
    return analytics.compute_skill_scores(_read_json(path))


@app.get("/jobs/{job_id}/opponent-strength")
def job_opponent_strength(job_id: str, user: dict = Depends(auth.current_user)):
    """How good was the opponent's team-preview pick, per match, and does that
    predict anything in this player's actual results? Not in the original
    section-8 contract - added for the type-overlap-risk analysis (see
    backend/type_synergy.py)."""
    job = _job_or_404(job_id, user)
    path = Path(job["dir"]) / "events.json"
    if not path.exists():
        raise HTTPException(409, f"events.json not ready yet (job status: {job['status']}, step: {job['step']})")
    return analytics.compute_opponent_strength(_read_json(path))


@app.get("/jobs/{job_id}/decision-windows")
def job_decision_windows(job_id: str, user: dict = Depends(auth.current_user)):
    """Per-turn, per-match: what each side had available (board, alive
    roster, switch options, moves already revealed this match) and what it
    actually chose - see decision_windows.py's module docstring. Frontend
    filters the flat list by `match` the same way it already does for
    /jobs/{id}/events. Returns [] for any match with no field_state/turn
    data (currently every Showdown-imported match - a stated, honest
    limitation, not a bug)."""
    job = _job_or_404(job_id, user)
    path = Path(job["dir"]) / "events.json"
    if not path.exists():
        raise HTTPException(409, f"events.json not ready yet (job status: {job['status']}, step: {job['step']})")
    return analytics.compute_decision_windows(_read_json(path))


@app.get("/jobs/{job_id}/strategic-analysis")
def job_strategic_analysis(job_id: str, user: dict = Depends(auth.current_user)):
    """Per match: a per-turn advantage-score/momentum timeline (with
    plain-language reasons), a resource-tracking summary, and conservative
    mistake-candidate flags - see strategic_analysis.py's module docstring
    for the load-bearing caveat that none of this is a calibrated model,
    only a bounded heuristic built on decision_windows.py. Returns an
    empty timeline for any match with no field_state/turn data (same
    limitation as /jobs/{id}/decision-windows, not a bug)."""
    job = _job_or_404(job_id, user)
    path = Path(job["dir"]) / "events.json"
    if not path.exists():
        raise HTTPException(409, f"events.json not ready yet (job status: {job['status']}, step: {job['step']})")
    return analytics.compute_strategic_analysis(_read_json(path))


@app.get("/jobs/{job_id}/battle-profile")
def job_battle_profile(job_id: str, user: dict = Depends(auth.current_user)):
    """Job-wide "overall skill set" profile (added 2026-07-09, tasks
    #234-237): rolls up /jobs/{id}/strategic-analysis's per-match/per-turn
    six reports across every match in this job - Position Score trend/band
    distribution, Speed Control/Threat Pressure favorability, screen uptime,
    momentum event tallies, Risk Management posture distribution, recurring
    mistake/win-condition patterns, and loss patterns. See analytics.
    compute_job_battle_profile's own docstring for exactly what's rolled up
    and how this differs from /jobs/{id}/skill-scores' separate, coarser
    heuristic. Returns null in the response body (not a 404/409) when the
    job has events.json but no match in it has any turns yet - same "not
    ready to report, not a zero" distinction the rest of this file follows."""
    job = _job_or_404(job_id, user)
    path = Path(job["dir"]) / "events.json"
    if not path.exists():
        raise HTTPException(409, f"events.json not ready yet (job status: {job['status']}, step: {job['step']})")
    return analytics.compute_job_battle_profile(_read_json(path))


@app.post("/jobs/{job_id}/coach", response_model=CoachAnswer)
def job_coach(job_id: str, body: CoachQuestion, user: dict = Depends(auth.current_user)):
    job = _job_or_404(job_id, user)
    d = Path(job["dir"])
    events_path = d / "events.json"
    if not events_path.exists():
        raise HTTPException(409, f"events.json not ready yet (job status: {job['status']}, step: {job['step']})")
    if not os.environ.get("GEMINI_API_KEY"):
        raise HTTPException(500, "GEMINI_API_KEY is not set on the server.")

    import coach_chat as cc   # imported lazily so a missing google-genai install doesn't break the whole API

    events = _read_json(events_path)
    transcript = None
    tpath = d / "transcript.json"
    if tpath.exists():
        transcript = _read_json(tpath)

    meta_ctx = cc.load_meta_context(str(d / "schema.json"), str(META_DIR))
    profile = (meta_ctx + "\n\n" if meta_ctx else "") + cc.profile_summary(events)
    refs = cc.referenced_matches(body.question, set(cc.by_match(events).keys()))
    extra = "\n".join(cc.match_block(events, transcript, m) for m in refs[:2])

    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    answer = cc.answer(client, "gemini-2.5-flash", [], profile, extra, body.question)
    # Logged for real usage insight (what are players actually asking their
    # coach) - see backend/audit.py. answer is capped, not because it's
    # sensitive, just to keep individual log entries bounded.
    audit.record("coach_question_asked", user_id=user["id"], scope="job", job_id=job_id,
                 question=body.question, answer=answer[:2000])
    return CoachAnswer(answer=answer)


# -------------------------------------------------------------- career -----
# Everything below aggregates across EVERY completed job this user has ever
# uploaded (not just one job_id) - see backend/career.py's docstring for why
# this was missing before and how the merge works. No job_id in any of these
# routes: the "job" here is implicitly "all of this user's matches, ever."

# since/until (both optional, 'YYYY-MM-DD') on every /career/* route below:
# narrows the merge down to only the upload sessions created in that window,
# via career.filter_by_date - see that function's own docstring for why this
# filters by whole SESSION (job) rather than by individual event timestamp.
# Left blank/omitted on both, every route below behaves exactly as it did
# before this filter existed ("All time"). Added 2026-07-09 for the combined
# "All Gameplay" view's date-range filter and period-comparison feature -
# GameplayDateFilter.jsx (frontend) is what actually sets these.
_DATE_PARAM_DOC = ("'YYYY-MM-DD' - only include Gameplay uploaded on or after this date. "
                   "Omit for no lower bound (start of time).")
_DATE_PARAM_DOC_UNTIL = ("'YYYY-MM-DD' - only include Gameplay uploaded on or before this date "
                        "(inclusive of the whole day). Omit for no upper bound (now).")


@app.get("/career/record")
def career_record(since: Optional[str] = Query(None, description=_DATE_PARAM_DOC),
                   until: Optional[str] = Query(None, description=_DATE_PARAM_DOC_UNTIL),
                   user: dict = Depends(auth.current_user)):
    merged, sessions = career.merge_user_events(user["id"])
    merged, sessions = career.filter_by_date(merged, sessions, since, until)
    return analytics.compute_record(merged)


@app.get("/career/report")
def career_report(since: Optional[str] = Query(None, description=_DATE_PARAM_DOC),
                   until: Optional[str] = Query(None, description=_DATE_PARAM_DOC_UNTIL),
                   user: dict = Depends(auth.current_user)):
    merged, sessions = career.merge_user_events(user["id"])
    merged, sessions = career.filter_by_date(merged, sessions, since, until)
    # No single format `rules` block applies across every job (different jobs
    # could in principle use different regulations/modes) - passing rules=None
    # makes compute_report fall back to "assume Tera is legal" for the combined
    # view. Precise enough for a career-wide summary; a per-session breakdown
    # (see /career/skill-scores/trend) is where format-specific nuance matters.
    return analytics.compute_report(merged)


@app.get("/career/matches")
def career_matches(since: Optional[str] = Query(None, description=_DATE_PARAM_DOC),
                    until: Optional[str] = Query(None, description=_DATE_PARAM_DOC_UNTIL),
                    user: dict = Depends(auth.current_user)):
    """Same merge_in-duration pattern as GET /jobs/{id}/matches/summary
    (see that endpoint's own comment) - duration_seconds never lived in
    events.json, only in each job's own matches.csv, so it has to be
    merged in separately here too. career.match_durations() handles the
    cross-job global-match-number remapping (see its own docstring for why
    this isn't just a third merge_user_events() return value). Note
    match_durations() is itself NOT date-filtered (it's keyed by the SAME
    global match numbers filter_by_date leaves untouched - see that
    function's docstring - so looking up by `row["match"]` below still finds
    the right duration even though the durations dict spans every session)."""
    merged, sessions = career.merge_user_events(user["id"])
    merged, sessions = career.filter_by_date(merged, sessions, since, until)
    rows = analytics.compute_match_list(merged)
    durations = career.match_durations(user["id"])
    for row in rows:
        row["duration_seconds"] = durations.get(row["match"])
    return rows


@app.get("/career/events")
def career_events(since: Optional[str] = Query(None, description=_DATE_PARAM_DOC),
                   until: Optional[str] = Query(None, description=_DATE_PARAM_DOC_UNTIL),
                   user: dict = Depends(auth.current_user)):
    """Raw merged events across every completed job this user has uploaded -
    the combined-view analog of GET /jobs/{id}/events. Each event carries
    `session` (1-based upload-session index) and `source_job_id` (which
    original job it came from - see career.merge_user_events' docstring),
    which the frontend uses to route per-match frame/replay requests back to
    the right job and to disable event-correction editing in combined mode
    (a corrected index only makes sense against one job's own events.json,
    not this merged array - see MatchSummary.jsx)."""
    merged, sessions = career.merge_user_events(user["id"])
    merged, sessions = career.filter_by_date(merged, sessions, since, until)
    return merged


@app.get("/career/opponent-strength")
def career_opponent_strength(since: Optional[str] = Query(None, description=_DATE_PARAM_DOC),
                              until: Optional[str] = Query(None, description=_DATE_PARAM_DOC_UNTIL),
                              user: dict = Depends(auth.current_user)):
    """Combined-view analog of GET /jobs/{id}/opponent-strength, computed
    over every match across every completed job this user has uploaded."""
    merged, sessions = career.merge_user_events(user["id"])
    merged, sessions = career.filter_by_date(merged, sessions, since, until)
    return analytics.compute_opponent_strength(merged)


@app.get("/career/battle-profile")
def career_battle_profile(since: Optional[str] = Query(None, description=_DATE_PARAM_DOC),
                           until: Optional[str] = Query(None, description=_DATE_PARAM_DOC_UNTIL),
                           user: dict = Depends(auth.current_user)):
    """Combined-view analog of GET /jobs/{id}/battle-profile (see that
    endpoint's docstring) - the job-wide "overall skill set" rollup, but
    computed across every match in every completed job this user has ever
    uploaded instead of just one job. Same null-not-404 contract: returns
    null in the response body when there's merged event data but no match
    in it has any turns yet."""
    merged, sessions = career.merge_user_events(user["id"])
    merged, sessions = career.filter_by_date(merged, sessions, since, until)
    return analytics.compute_job_battle_profile(merged)


@app.get("/career/skill-scores")
def career_skill_scores(since: Optional[str] = Query(None, description=_DATE_PARAM_DOC),
                         until: Optional[str] = Query(None, description=_DATE_PARAM_DOC_UNTIL),
                         user: dict = Depends(auth.current_user)):
    """All-time skill scores across every match this user has ever uploaded -
    the single blended number. See /career/skill-scores/trend for the
    session-by-session breakdown that actually shows improvement over time;
    this endpoint alone can only ever answer "how good am I, overall." With
    since/until set, "all-time" narrows to just that window - this is the
    endpoint the period-comparison feature calls twice (once per period) to
    get each side's overall/tempo/adaptability/execution/closing numbers."""
    merged, sessions = career.merge_user_events(user["id"])
    merged, sessions = career.filter_by_date(merged, sessions, since, until)
    return analytics.compute_skill_scores(merged)


@app.get("/career/skill-scores/trend")
def career_skill_scores_trend(since: Optional[str] = Query(None, description=_DATE_PARAM_DOC),
                               until: Optional[str] = Query(None, description=_DATE_PARAM_DOC_UNTIL),
                               user: dict = Depends(auth.current_user)):
    """The actual "track how the player has improved" endpoint: one entry per
    upload session (oldest first), each with a `per_session` skill-score
    snapshot (computed from ONLY that session's matches - the real trend
    signal) and a `cumulative` snapshot (computed from every match up through
    that session - noisier early, smooths out as more data accumulates). See
    backend/career.py's compute_skill_score_trend docstring for why both are
    returned rather than picking one. since/until narrow which sessions
    appear at all (each session's own per_session/cumulative snapshots are
    still computed from the FILTERED merged_events, so a cumulative value
    here reflects "everything up through this session, WITHIN the filtered
    window" - consistent with every other /career/* route's since/until
    semantics, not a separate meaning)."""
    merged, sessions = career.merge_user_events(user["id"])
    merged, sessions = career.filter_by_date(merged, sessions, since, until)
    return career.compute_skill_score_trend(merged, sessions)


@app.post("/career/coach", response_model=CoachAnswer)
def career_coach(body: CoachQuestion, user: dict = Depends(auth.current_user)):
    """Same coach as POST /jobs/{id}/coach, but grounded in the player's
    ENTIRE upload history instead of one job - the profile it builds includes
    a SESSION-BY-SESSION PROGRESSION block (coach_chat.session_progression_summary)
    so it can actually answer "have I improved" questions, not just describe
    one blended aggregate. See coach_chat.py's SYSTEM prompt update for how
    the model is told to use that block."""
    if not os.environ.get("GEMINI_API_KEY"):
        raise HTTPException(500, "GEMINI_API_KEY is not set on the server.")

    merged, sessions = career.merge_user_events(user["id"])
    if not merged:
        raise HTTPException(409, "No completed jobs yet - upload and finish at least one job first.")

    import coach_chat as cc   # imported lazily so a missing google-genai install doesn't break the whole API

    # No single schema.json applies "career-wide" (different jobs could in
    # principle use different regulations) - use the MOST RECENT session's
    # job dir as the best available current-format context, same spirit as
    # /career/report's rules=None fallback above.
    latest_schema_path = META_DIR / "_none_.json"
    if sessions:
        candidate = jobs.job_dir(sessions[-1]["job_id"], user["id"])
        if candidate and (candidate / "schema.json").exists():
            latest_schema_path = candidate / "schema.json"
    meta_ctx = cc.load_meta_context(str(latest_schema_path), str(META_DIR))
    session_ctx = cc.session_progression_summary(merged, sessions)
    profile = (meta_ctx + "\n\n" if meta_ctx else "") + cc.profile_summary(merged) \
        + ("\n\n" + session_ctx if session_ctx else "")
    refs = cc.referenced_matches(body.question, set(cc.by_match(merged).keys()))
    extra = "\n".join(cc.match_block(merged, None, m) for m in refs[:2])

    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    answer = cc.answer(client, "gemini-2.5-flash", [], profile, extra, body.question)
    audit.record("coach_question_asked", user_id=user["id"], scope="career",
                 question=body.question, answer=answer[:2000])
    return CoachAnswer(answer=answer)


# ------------------------------------------------------- coach sharing -----
# Player-generated shareable links + a persistent coach/student roster + notes
# - see backend/coaching.py's module docstring for the full privacy model.
# Nothing here is ever visible without a valid, non-revoked, non-expired
# token that the PLAYER themselves generated - there is no directory or
# search across accounts anywhere in this section.

@app.post("/account/share-links")
def create_share_link(body: ShareLinkCreate, user: dict = Depends(auth.current_user)):
    """The player's own action: generates a new link. `expires_in_days=None`
    (the default) means it never expires on its own - stays active until
    manually revoked. The frontend builds the actual shareable URL from this
    token (e.g. `${origin}/coach/${token}`) - this backend has no reliable
    way to know its own public-facing URL, especially behind a dev proxy."""
    return coaching.create_share_link(user["id"], label=body.label, expires_in_days=body.expires_in_days)


@app.get("/account/share-links")
def list_share_links(user: dict = Depends(auth.current_user)):
    """Every link this player has ever generated, including expired/revoked
    ones (their own management view needs to show those too)."""
    return coaching.list_share_links(user["id"])


@app.delete("/account/share-links/{token}")
def revoke_share_link(token: str, user: dict = Depends(auth.current_user)):
    ok = coaching.revoke_share_link(user["id"], token)
    if not ok:
        raise HTTPException(404, "No such share link (or it isn't yours).")
    return {"revoked": True}


@app.get("/account/coaching-notes")
def my_coaching_notes(user: dict = Depends(auth.current_user)):
    """A player's own read-only view of every note ANY coach has left about
    them, across every coach who's ever added them to a roster - this is
    what closes the loop and is the whole point of the notes feature, not
    just a one-way "coach observes silently" tool."""
    return coaching.list_notes_about_player(user["id"])


# --------------------------------------------------------------- API keys --
# Long-lived, per-user credentials for external clients that can't hold a
# short-lived Supabase session - see backend/api_keys.py's module docstring
# (the planned Pokemon Showdown browser extension is the first consumer).

@app.post("/account/api-keys")
def create_api_key(body: ApiKeyCreate, user: dict = Depends(auth.current_user)):
    """Returns the plaintext key in the `key` field - the ONLY time it's
    ever shown. Every later GET /account/api-keys call sees only key_prefix,
    never enough to authenticate with (see api_keys.py's module docstring
    for why only a hash is stored)."""
    return api_keys.create_api_key(user["id"], label=body.label)


@app.get("/account/api-keys")
def list_api_keys(user: dict = Depends(auth.current_user)):
    """Every key this player has ever generated, including revoked ones
    (their own management view needs to show those too) - metadata only,
    never a usable credential."""
    return api_keys.list_api_keys(user["id"])


@app.delete("/account/api-keys/{key_id}")
def revoke_api_key(key_id: str, user: dict = Depends(auth.current_user)):
    ok = api_keys.revoke_api_key(user["id"], key_id)
    if not ok:
        raise HTTPException(404, "No such API key (or it isn't yours).")
    return {"revoked": True}


@app.get("/coach-view/{token}")
def coach_view(token: str):
    """PUBLIC - deliberately no `user: dict = Depends(auth.current_user)`
    here at all. This is the ONE unauthenticated read path in this entire
    backend, and it's intentionally narrow: aggregate-only stats for
    whichever single player generated this exact token, nothing else. A
    signed-in coach who wants this player on their persistent roster (with
    notes) uses POST /coach/students instead - visiting this URL alone adds
    nothing to anyone's account, it's just a read."""
    resolved = coaching.resolve_share_link(token)
    if resolved is None:
        raise HTTPException(404, "This link is invalid, has been revoked, or has expired.")
    coaching.touch_share_link(token)
    profile = coaching.compute_playstyle_profile(resolved["user_id"])
    profile["shared_label"] = resolved.get("label")
    return profile


@app.post("/coach/students")
def add_student(body: RedeemShareLink, user: dict = Depends(auth.current_user)):
    """Redeems a share link into the CALLING account's own student roster -
    this is what makes the relationship persistent (a roster entry, notes)
    rather than a one-off view. Idempotent: redeeming the same link twice
    just returns the existing roster entry."""
    result = coaching.add_student(user["id"], body.token)
    if result is None:
        raise HTTPException(404, "This link is invalid, has been revoked, or has expired.")
    return result


@app.get("/coach/students")
def list_students(user: dict = Depends(auth.current_user)):
    return coaching.list_students(user["id"])


def _student_or_404(coach_user_id: str, player_user_id: str) -> dict:
    """Every /coach/students/{player_id}/... route needs this - a coach can
    only see a profile/notes for someone actually on THEIR OWN roster right
    now (see coaching.remove_student's docstring: removing a student
    immediately revokes this, independent of the underlying share link)."""
    link = coaching.get_student_link(coach_user_id, player_user_id)
    if link is None:
        raise HTTPException(404, "No such student on your roster.")
    return link


@app.patch("/coach/students/{player_user_id}")
def rename_student(player_user_id: str, body: RenameStudent, user: dict = Depends(auth.current_user)):
    _student_or_404(user["id"], player_user_id)
    coaching.rename_student(user["id"], player_user_id, body.label)
    return {"renamed": True}


@app.delete("/coach/students/{player_user_id}")
def remove_student(player_user_id: str, user: dict = Depends(auth.current_user)):
    _student_or_404(user["id"], player_user_id)
    coaching.remove_student(user["id"], player_user_id)
    return {"removed": True}


@app.get("/coach/students/{player_user_id}/profile")
def student_profile(player_user_id: str, user: dict = Depends(auth.current_user)):
    """Same aggregate-only shape GET /coach-view/{token} returns - a coach
    sees identical data whether they're viewing through a fresh link or
    their own saved roster."""
    _student_or_404(user["id"], player_user_id)
    return coaching.compute_playstyle_profile(player_user_id)


@app.get("/coach/students/{player_user_id}/notes")
def student_notes(player_user_id: str, user: dict = Depends(auth.current_user)):
    """This coach's own notes for this one student - not every coach's notes
    (see GET /account/coaching-notes for the player-side "everyone's notes
    about me" view)."""
    _student_or_404(user["id"], player_user_id)
    return coaching.list_notes_by_coach_for_student(user["id"], player_user_id)


@app.post("/coach/students/{player_user_id}/notes")
def add_student_note(player_user_id: str, body: NoteCreate, user: dict = Depends(auth.current_user)):
    _student_or_404(user["id"], player_user_id)
    return coaching.add_note(user["id"], player_user_id, body.text,
                             coach_email=user.get("email") or "", category=body.category)


@app.patch("/coach/notes/{note_id}")
def update_note(note_id: str, body: NoteUpdate, user: dict = Depends(auth.current_user)):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    result = coaching.update_note(user["id"], note_id, **fields)
    if result is None:
        raise HTTPException(404, "No such note (or it isn't yours).")
    return result


@app.delete("/coach/notes/{note_id}")
def delete_note(note_id: str, user: dict = Depends(auth.current_user)):
    ok = coaching.delete_note(user["id"], note_id)
    if not ok:
        raise HTTPException(404, "No such note (or it isn't yours).")
    return {"deleted": True}


# ------------------------------------------------------------ telemetry -----
# Lightweight frontend usage tracking (tab views, UI interactions) - writes
# through the SAME internal audit log the backend's own action-level events
# already use (job_created, coach_question_asked, share_link_created, ...),
# not a separate analytics vendor. Requires a signed-in user like every other
# endpoint here: the frontend only ever calls this from inside the
# authenticated dashboard shell (see App.jsx's `ready` gate), so there's no
# case where a real call would arrive without a valid session anyway.

@app.post("/telemetry/event")
def track_event(body: ClientEvent, user: dict = Depends(auth.current_user)):
    """See backend/audit.py's module docstring for the fail-soft guarantee
    this inherits: a broken telemetry write is never allowed to be the
    reason a real user-facing request errors, so this always returns 200.
    `payload` is nested under its own key (rather than spread as **kwargs)
    so a frontend caller can never accidentally collide with `user_id` or
    `event_type`, which audit.record() also uses as top-level fields."""
    audit.record(f"client:{body.event_type}", user_id=user["id"], payload=body.payload)
    return {"tracked": True}


# ---------------------------------------------------------------- meta -----
# Project-level game-format data (type chart, legal-species notes, etc.) -
# not scoped to a user, so no auth dependency here.

@app.get("/meta/{format_name}")
def get_meta(format_name: str):
    path = META_DIR / f"{format_name}.json"
    if not path.exists():
        raise HTTPException(
            404,
            f"No meta/{format_name}.json yet. Run `py meta_build.py` in poc-starter/ "
            "first (builds the type chart + your own usage stats).",
        )
    return _read_json(path)
