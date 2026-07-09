"""
"Career" aggregation - merges events.json across EVERY completed job a user
has ever uploaded into one chronological event stream, so the existing
analytics functions (compute_record/compute_report/compute_skill_scores/
compute_match_list in backend/analytics.py) can be reused UNCHANGED over
"all matches this player has ever uploaded," not just one job's worth.

Why this didn't already exist: every job already gets its own folder
(jobs/<job_id>/events.json) and already belongs to a user_id (see
backend/jobs.py), and old job folders are never deleted (see
ARCHITECTURE_HANDOFF.md's data-retention note) - so all the raw data needed
for this was already sitting on disk. What was missing was purely the
merge/bookkeeping step: each job numbers its own matches starting from 1
(analyze_matches.py has no notion of "this is job #3, not job #1"), so job A's
"match 1" and job B's "match 1" collide if you just concatenate their
events.json files naively. This module remaps those into one global,
chronologically-ordered match sequence and tags every event with which
upload SESSION it came from - the session boundary is what makes "track how
the player has improved" answerable at all: skill_scores.compute_skill_scores()
already aggregates cleanly over any list of events, but averaged over
everything-at-once it can only ever tell you "how good am I, overall" - never
"was session 5 better than session 1." See compute_skill_score_trend() below
for the piece that actually answers that.

Deliberately does NOT persist a merged file anywhere - every call re-reads
each completed job's events.json from disk and re-merges from scratch. This
project is solo-user-scale (a handful to a few dozen jobs, each a few dozen
matches at most), so recomputing on every request is cheap and has zero
cache-invalidation risk (a corrected event, a newly-completed job, or a
deleted job all "just work" on the next call, no invalidation logic needed).
Revisit if/when job counts get large enough that this becomes slow.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent   # poc-starter/ - see analytics.py's identical pattern
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from . import jobs as _jobs


def _created_at_key(value) -> float:
    """created_at is a float unix timestamp in local dev mode (time.time()/
    st_mtime - see backend/jobs.py) but an ISO-8601 string in real Supabase
    (a `timestamptz` column, returned as text by the Python client) - this
    normalizes either shape to a comparable float so jobs sort chronologically
    the same way regardless of which mode produced them. Unparseable/missing
    values sort first (0.0) rather than crashing or silently reordering
    everything after them."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()
    except (ValueError, TypeError):
        return 0.0


def list_completed_jobs_chronological(user_id: str) -> list:
    """Every 'done' job this user owns, oldest first - the order matches are
    actually assumed to have happened in real life, which is the whole basis
    for "session 1 vs session 5" meaning anything. Excludes queued/running/
    failed jobs (no usable events.json yet, or ever, for a failed one).

    Filters by user_id AGAIN here even though _jobs.list_jobs(user_id) is
    supposed to already scope to that user - belt-and-suspenders, the same
    defensive-filtering spirit backend/jobs.py's own update_job() uses. This
    isn't paranoia for no reason: local dev mode's list_jobs() deliberately
    ignores its user_id argument and returns EVERY local job (there's only
    ever one real user in that mode - see backend/jobs.py's docstring), so
    without this second filter a career aggregation could silently pull in
    another account's matches the moment more than one user_id ever appears
    in local-mode testing. Real Supabase-backed list_jobs() already filters
    correctly, so this is a no-op there - just cheap insurance."""
    all_jobs = _jobs.list_jobs(user_id)
    done = [j for j in all_jobs if j.get("status") == "done" and j.get("user_id") == user_id]
    done.sort(key=lambda j: _created_at_key(j.get("created_at")))
    return done


def _load_job_events(job_dir: str) -> list:
    path = Path(job_dir) / "events.json"
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def merge_user_events(user_id: str):
    """The core of this module. Returns (merged_events, sessions):

    merged_events: every event from every completed job, concatenated, with
    two fields added/overwritten on each event:
      - "match": remapped to a GLOBAL sequence number, unique across every
        job (was only unique within one job before). Events with no "match"
        (there are a few event types not tied to a specific match) are left
        alone - remapping only touches events that actually had one.
      - "session": 1-based index of which upload this event came from, in
        chronological order. This is the field everything else in this
        module (and coach_chat's session_progression_summary) keys off of to
        tell "session 3" apart from "session 1," which a flat merged list
        alone can't do.
      - "source_job_id": the original job_id, kept for traceability/debugging
        and so a frontend could still deep-link back to "open this match in
        its original job" if ever wanted.

    sessions: one dict per completed job, in the same chronological order,
    with {"session", "job_id", "created_at", "matches_in_session",
    "source_type", "video"} - the metadata a trend chart or coach-chat
    session summary needs, without having to re-derive it from merged_events
    every time.
    """
    merged_events = []
    sessions = []
    global_match_offset = 0

    for session_index, job in enumerate(list_completed_jobs_chronological(user_id), start=1):
        events = _load_job_events(job["dir"])
        if not events:
            continue   # a 'done' job with no readable events.json - skip, don't crash the whole merge

        local_matches = sorted({e["match"] for e in events if e.get("match") is not None})
        remap = {m: i + 1 + global_match_offset for i, m in enumerate(local_matches)}

        for e in events:
            e2 = dict(e)
            if e2.get("match") in remap:
                e2["match"] = remap[e2["match"]]
            e2["session"] = session_index
            e2["source_job_id"] = job["job_id"]
            merged_events.append(e2)

        sessions.append({
            "session": session_index,
            "job_id": job["job_id"],
            "created_at": job.get("created_at"),
            "matches_in_session": len(local_matches),
            "source_type": job.get("source_type"),
            "video": job.get("video"),
        })
        global_match_offset += len(local_matches)

    return merged_events, sessions


def match_durations(user_id: str) -> dict:
    """Global match number -> duration_seconds (float), for every match this
    user has EVER uploaded that has a matches.csv on disk with that data.

    Why this exists as its own function rather than a third merge_user_events()
    return value: duration_seconds never lived in events.json at all - it's
    written separately, per job, to that job's own matches.csv by
    structure_pass.py (the actual detected match start/end timestamps -
    see backend/main.py's job_matches_summary(), which does the identical
    merge for a SINGLE job's /jobs/{id}/matches/summary). Threading a third
    value out of merge_user_events() would mean touching every one of its
    6+ existing call sites in main.py/tests for a value only ONE endpoint
    (GET /career/matches) actually needs - a small, self-contained function
    here is a smaller, safer change, consistent with this module's own
    "recompute from disk on every call, no shared cache" design already
    described above.

    Independently re-derives the SAME local-match -> global-match remap
    merge_user_events() builds, by walking the same
    list_completed_jobs_chronological(user_id) order and incrementing the
    same running offset by each job's own local match count - as long as
    both functions keep iterating jobs in that same chronological order
    (they do, and both derive local_matches from that job's own events the
    same way), the global match numbers this produces line up exactly with
    the ones merge_user_events() assigns. This does mean the remap logic
    exists in two places in this file rather than one; that duplication was
    judged worth it here specifically to avoid a wider, riskier signature
    change - see this docstring's previous paragraph.

    Missing key = duration genuinely unknown for that match (an older job
    predating duration_seconds, a matches.csv that failed to parse, a match
    number matches.csv doesn't mention, or a job with no matches.csv at all
    - e.g. a Showdown-import job, which was never a video and has no
    detected-timestamp duration to report). Callers should use dict.get(match)
    and treat a missing/None value as "not available," never as 0 seconds -
    the same "skip, don't guess" rule this whole project applies to every
    other unknown/unreadable value."""
    import csv

    durations = {}
    global_match_offset = 0
    for job in list_completed_jobs_chronological(user_id):
        events = _load_job_events(job["dir"])
        if not events:
            continue
        local_matches = sorted({e["match"] for e in events if e.get("match") is not None})
        remap = {m: i + 1 + global_match_offset for i, m in enumerate(local_matches)}

        matches_csv = Path(job["dir"]) / "matches.csv"
        if matches_csv.exists():
            try:
                with open(matches_csv, newline="", encoding="utf-8") as f:
                    for r in csv.DictReader(f):
                        try:
                            local_m = int(r["match"])
                            dur = float(r["duration_seconds"])
                        except (KeyError, ValueError, TypeError):
                            continue   # unparseable row - skip it, don't guess a duration
                        if local_m in remap:
                            durations[remap[local_m]] = dur
            except OSError:
                pass   # unreadable matches.csv - this job's durations just stay missing

        global_match_offset += len(local_matches)
    return durations


def events_for_session(merged_events: list, session_index: int) -> list:
    """Only the events from ONE upload session, isolated - the "how did I do
    in just this practice session" view (used for the per-session/isolated
    half of the skill-score trend, see compute_skill_score_trend below)."""
    return [e for e in merged_events if e.get("session") == session_index]


def events_through_session(merged_events: list, session_index: int) -> list:
    """Every event from session 1 through `session_index` inclusive - the
    growing-window "everything I know so far" view (used for the cumulative
    half of the skill-score trend)."""
    return [e for e in merged_events if e.get("session") is not None and e["session"] <= session_index]


def compute_skill_score_trend(merged_events: list, sessions: list) -> list:
    """The actual "track how the player has improved" answer: one entry per
    upload session, each carrying BOTH a `per_session` skill-score snapshot
    (computed from ONLY that session's matches - the real improvement
    signal, since it isn't diluted by everything that came before) and a
    `cumulative` snapshot (computed from every match up through that session
    - noisier early on, converges as more data piles up, useful for "what's
    my all-time-so-far number right now"). Either can be None for an early
    session with too few/no decided matches - skill_scores.compute_skill_scores
    already returns None in that case (see its own docstring); this just
    passes that through rather than papering over it with a fake 0.

    Deliberately returns BOTH rather than picking one - see the "Both" choice
    made when this feature was scoped (ARCHITECTURE_HANDOFF.md), since a
    single blended number can't serve "did I improve" (needs per-session) and
    "what's true across my whole sample" (needs cumulative) at the same
    time."""
    import skill_scores as _ss   # lazy: keeps this module importable even if skill_scores.py moves/changes

    trend = []
    for s in sessions:
        idx = s["session"]
        per_session = _ss.compute_skill_scores(events_for_session(merged_events, idx))
        cumulative = _ss.compute_skill_scores(events_through_session(merged_events, idx))
        trend.append({
            "session": idx,
            "job_id": s["job_id"],
            "created_at": s["created_at"],
            "matches_in_session": s["matches_in_session"],
            "per_session": per_session,
            "cumulative": cumulative,
        })
    return trend
