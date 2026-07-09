"""
Coach-sharing: lets a player generate a link that gives a signed-in coach
read-only access to an AGGREGATE-ONLY performance profile (skill scores +
trend, coaching flags, matchup weaknesses, win-rate-by-lead/bring) - never
raw match video, per-event timelines, or reference frames. Coaches who
redeem a link get that player added to a persistent "students" roster and
can leave notes/coaching-plan suggestions the player sees on their own
dashboard.

CORE PRIVACY RULE (the whole reason this module exists as a separate,
narrow surface rather than just loosening the existing /jobs or /career
endpoints): every account stays completely private by default. There is no
directory, no search, no "find a coach" listing, and no way to see ANY
other account's data without a valid, non-revoked, non-expired share
token that THAT account's owner explicitly generated and handed out
themselves. GET /coach-view/{token} (see main.py) is the only unauthenticated
read path this whole backend exposes - deliberately narrow (aggregate-only,
one token = one player) rather than a general "public profile" concept.

Anyone can act as a "coach" simply by redeeming a link into their own
account's roster - there's no separate coach role/signup flow, reusing the
same plain accounts system as everything else in this app (see
backend/auth.py). A single account can simultaneously be a "player" (with
their own share links + coaching notes received) and a "coach" (with their
own student roster) - these are just two different sets of rows keyed by
the same user_id, not two account types.

LOCAL DEV MODE (see backend/auth.py's configured()): falls back to
module-level in-memory dicts, exactly like backend/jobs.py. Note this makes
the FEATURE itself not very meaningful in local dev mode specifically -
auth.current_user() always returns the same LOCAL_USER there, so "coach"
and "player" would literally be the same account - but it still exercises
every code path (create/redeem/note/revoke) without crashing, which is what
local dev mode is for everywhere else in this app too.
"""

import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from . import audit
from .auth import configured, get_service_client

SHARE_LINKS_TABLE = "share_links"
COACH_STUDENTS_TABLE = "coach_student_links"
COACH_NOTES_TABLE = "coach_notes"

# ---- local dev mode (no Supabase configured) -------------------------------
_LOCAL_SHARE_LINKS: dict = {}          # token -> row
_LOCAL_COACH_STUDENTS: dict = {}       # (coach_user_id, player_user_id) -> row
_LOCAL_COACH_NOTES: dict = {}          # note_id -> row
# -----------------------------------------------------------------------------


def _parse_ts(value) -> float:
    """Same dual-shape problem backend/career.py's _created_at_key solves -
    local dev mode stores plain float unix seconds (time.time()), real
    Supabase returns an ISO-8601 string for any timestamptz column. This
    normalizes either to a comparable float. None/unparseable -> 0.0 (sorts/
    compares as "already expired" is the WRONG default for an expiry check
    specifically, so callers checking expiry must treat None as "no
    expiration" themselves BEFORE calling this - see resolve_share_link)."""
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


def _to_iso(ts: float) -> str:
    """The other direction of _parse_ts's dual-shape conversion: every
    created_at/updated_at/expires_at/revoked_at/last_viewed_at/added_at
    column in supabase_schema.sql is `timestamptz`, which Postgres can't
    parse a raw unix-seconds float as (this exact bug shipped and surfaced
    as "invalid input syntax for type timestamp with time zone" the first
    time a real Supabase-backed insert/update sent one). Local dev mode
    keeps using plain float time.time() values - only the Supabase-bound
    copy of a row/update dict needs to go through this."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _new_id() -> str:
    return secrets.token_hex(12)


# ------------------------------------------------------------- share links --

def create_share_link(user_id: str, label: Optional[str] = None,
                       expires_in_days: Optional[int] = None) -> dict:
    """Generates a new unguessable token (secrets.token_urlsafe - not a
    sequential/guessable id like job_id's uuid.hex, since a share token IS
    the entire access control for this feature, unlike a job_id which is
    only ever looked up alongside an ownership check). `label` is the
    PLAYER's own private note about who this link is for (e.g. "link I sent
    Coach Sarah") - never shown to whoever holds the link; see
    resolve_share_link's docstring for what a viewer actually sees.
    `expires_in_days=None` means the link never expires on its own and stays
    active until manually revoked - the player chooses this per-link at
    creation time, matching the "give the player the option" call made when
    this feature was scoped."""
    token = secrets.token_urlsafe(24)
    now = time.time()
    expires_at = (now + expires_in_days * 86400.0) if expires_in_days else None
    row = {
        "token": token, "owner_user_id": user_id, "label": label,
        "expires_at": expires_at, "revoked_at": None,
        "created_at": now, "last_viewed_at": None,
    }
    if not configured():
        _LOCAL_SHARE_LINKS[token] = row
        audit.record("share_link_created", user_id=user_id, token=token, label=label,
                     expires_in_days=expires_in_days)
        return dict(row)
    supabase_row = {**row, "created_at": _to_iso(now),
                    "expires_at": _to_iso(expires_at) if expires_at else None}
    get_service_client().table(SHARE_LINKS_TABLE).insert(supabase_row).execute()
    audit.record("share_link_created", user_id=user_id, token=token, label=label,
                 expires_in_days=expires_in_days)
    return row


def list_share_links(user_id: str) -> list:
    """Every link this player has ever generated (active, expired, and
    revoked all included - the player's own management view needs to show
    revoked/expired links too, e.g. so they can tell "this one I already
    turned off" apart from "this one's still live"). Newest first."""
    if not configured():
        rows = [r for r in _LOCAL_SHARE_LINKS.values() if r["owner_user_id"] == user_id]
    else:
        resp = (get_service_client().table(SHARE_LINKS_TABLE).select("*")
                .eq("owner_user_id", user_id).execute())
        rows = resp.data or []
    return sorted(rows, key=lambda r: _parse_ts(r.get("created_at")), reverse=True)


def revoke_share_link(user_id: str, token: str) -> bool:
    """Immediately and permanently disables a link (sets revoked_at) -
    resolve_share_link() checks this on every read, so an already-open
    coach-view tab stops working on its NEXT reload, not retroactively (no
    session to invalidate, since the public view never required signing
    in). Scoped to user_id: you can only revoke your OWN links - same
    ownership-in-the-query-itself pattern as backend/jobs.py's update_job()."""
    if not configured():
        row = _LOCAL_SHARE_LINKS.get(token)
        if row is None or row["owner_user_id"] != user_id:
            return False
        row["revoked_at"] = time.time()
        audit.record("share_link_revoked", user_id=user_id, token=token)
        return True
    resp = (get_service_client().table(SHARE_LINKS_TABLE)
            .update({"revoked_at": _to_iso(time.time())})
            .eq("token", token).eq("owner_user_id", user_id).execute())
    ok = bool(resp.data)
    if ok:
        audit.record("share_link_revoked", user_id=user_id, token=token)
    return ok


def resolve_share_link(token: str) -> Optional[dict]:
    """The one function both the public GET /coach-view/{token} endpoint and
    the coach's "redeem into my roster" endpoint call to answer "is this
    token currently valid, and whose data does it point at." Returns
    {"user_id", "label"} or None - collapsing "token never existed," "token
    was revoked," and "token expired" into the same single None result
    (never distinguishes which, the same "a stranger's job_id 404s exactly
    like a made-up one" principle backend/jobs.py's get_job() already uses -
    telling an attacker WHY a token doesn't work is strictly more
    information than telling them it doesn't work)."""
    if not configured():
        row = _LOCAL_SHARE_LINKS.get(token)
    else:
        resp = (get_service_client().table(SHARE_LINKS_TABLE).select("*")
                .eq("token", token).limit(1).execute())
        row = resp.data[0] if resp.data else None
    if row is None or row.get("revoked_at"):
        return None
    if row.get("expires_at") is not None and _parse_ts(row["expires_at"]) < time.time():
        return None
    return {"user_id": row["owner_user_id"], "label": row.get("label")}


def touch_share_link(token: str) -> None:
    """Best-effort "someone just viewed this" timestamp, so the player's own
    link-management view can show last_viewed_at (a real signal of "yes,
    this link is actually being used"). Deliberately swallow-on-failure -
    a broken analytics timestamp should never be the reason a real view
    request fails."""
    try:
        now = time.time()
        if not configured():
            row = _LOCAL_SHARE_LINKS.get(token)
            if row is not None:
                row["last_viewed_at"] = now
            audit.record("share_link_viewed", token=token)
            return
        get_service_client().table(SHARE_LINKS_TABLE).update(
            {"last_viewed_at": _to_iso(now)}).eq("token", token).execute()
        audit.record("share_link_viewed", token=token)
    except Exception:
        pass


# --------------------------------------------------------- student rosters --

def add_student(coach_user_id: str, token: str) -> Optional[dict]:
    """Redeems a share link into the calling account's own "students"
    roster. Returns the new (or already-existing - this is idempotent,
    redeeming the same link twice just returns the existing roster entry
    rather than erroring or duplicating it) roster row, or None if the
    token isn't currently valid (see resolve_share_link).

    The roster row's default coach_label is the LINK's own label if the
    player set one, else a generic "Player <first 6 chars of token>" -
    every roster entry needs SOME distinguishing text even when a player
    left their link's label blank, but the coach can always rename it
    afterward (see rename_student). Deliberately does NOT surface the
    player's account email here or anywhere else in this module - a coach
    only ever learns whatever label the PLAYER chose to attach to the
    link they generated, never the underlying account identity, unless the
    player put their own name in that label themselves."""
    resolved = resolve_share_link(token)
    if resolved is None:
        return None
    player_user_id = resolved["user_id"]
    existing = get_student_link(coach_user_id, player_user_id)
    if existing is not None:
        return existing

    default_label = resolved.get("label") or f"Player {token[:6]}"
    row = {
        "id": _new_id(), "coach_user_id": coach_user_id, "player_user_id": player_user_id,
        "share_token": token, "coach_label": default_label, "added_at": time.time(),
    }
    if not configured():
        _LOCAL_COACH_STUDENTS[(coach_user_id, player_user_id)] = row
        audit.record("student_added", coach_user_id=coach_user_id, player_user_id=player_user_id)
        return dict(row)
    supabase_row = {**row, "added_at": _to_iso(row["added_at"])}
    get_service_client().table(COACH_STUDENTS_TABLE).insert(supabase_row).execute()
    audit.record("student_added", coach_user_id=coach_user_id, player_user_id=player_user_id)
    return row


def get_student_link(coach_user_id: str, player_user_id: str) -> Optional[dict]:
    """The ownership check every per-student endpoint (profile/notes) needs:
    "does this coach actually have this player in their roster right now."
    A coach removing a student (see remove_student) immediately revokes
    their access to that player's profile/notes - independent of whether
    the underlying share link is still valid, since redeeming a link and
    staying on someone's roster are two separate, separately-revocable
    steps (the player can also invalidate access entirely by revoking the
    link itself - see revoke_share_link)."""
    if not configured():
        return _LOCAL_COACH_STUDENTS.get((coach_user_id, player_user_id))
    resp = (get_service_client().table(COACH_STUDENTS_TABLE).select("*")
            .eq("coach_user_id", coach_user_id).eq("player_user_id", player_user_id)
            .limit(1).execute())
    return resp.data[0] if resp.data else None


def list_students(coach_user_id: str) -> list:
    """This coach's whole roster, newest-added first."""
    if not configured():
        rows = [r for r in _LOCAL_COACH_STUDENTS.values() if r["coach_user_id"] == coach_user_id]
    else:
        resp = (get_service_client().table(COACH_STUDENTS_TABLE).select("*")
                .eq("coach_user_id", coach_user_id).execute())
        rows = resp.data or []
    return sorted(rows, key=lambda r: _parse_ts(r.get("added_at")), reverse=True)


def rename_student(coach_user_id: str, player_user_id: str, label: str) -> bool:
    """The coach's own nickname for this student - independent of whatever
    label the player themselves set on the share link (see add_student's
    docstring for why those are two separate fields)."""
    if not configured():
        row = _LOCAL_COACH_STUDENTS.get((coach_user_id, player_user_id))
        if row is None:
            return False
        row["coach_label"] = label
        return True
    resp = (get_service_client().table(COACH_STUDENTS_TABLE)
            .update({"coach_label": label})
            .eq("coach_user_id", coach_user_id).eq("player_user_id", player_user_id).execute())
    return bool(resp.data)


def remove_student(coach_user_id: str, player_user_id: str) -> bool:
    """Removes a student from THIS coach's roster only - does not touch the
    underlying share link (the player's own link stays valid for whoever
    else might hold it, and the player can still generate new ones) and
    does not delete this coach's past notes about that student (kept for
    the coach's own record even after removal; the player still sees them
    on their own dashboard too - a note, once written, doesn't disappear
    just because the roster relationship ended)."""
    if not configured():
        removed = _LOCAL_COACH_STUDENTS.pop((coach_user_id, player_user_id), None) is not None
        if removed:
            audit.record("student_removed", coach_user_id=coach_user_id, player_user_id=player_user_id)
        return removed
    resp = (get_service_client().table(COACH_STUDENTS_TABLE).delete()
            .eq("coach_user_id", coach_user_id).eq("player_user_id", player_user_id).execute())
    ok = bool(resp.data)
    if ok:
        audit.record("student_removed", coach_user_id=coach_user_id, player_user_id=player_user_id)
    return ok


# ------------------------------------------------------------------- notes --

def add_note(coach_user_id: str, player_user_id: str, text: str,
             coach_email: str, category: Optional[str] = None) -> dict:
    """`coach_email` is denormalized onto the note at creation time (passed
    in by the caller/endpoint, which already has it from the verified
    session - see backend/auth.py's current_user()) rather than resolved
    later from coach_user_id - this app has no general "look up any
    account's email by user_id" capability, and adding one just for this
    would be a bigger surface than a player's dashboard actually needs. The
    tradeoff, stated plainly: if a coach's email changes later, old notes
    still show whatever email was current when each note was written, not
    their latest one. `category` is freeform (e.g. "general" |
    "coaching_plan" | "skill_focus") - not an enum, so a coach isn't ever
    blocked from adding a note because their exact wording doesn't match a
    fixed list."""
    row = {
        "id": _new_id(), "coach_user_id": coach_user_id, "player_user_id": player_user_id,
        "coach_email": coach_email, "text": text, "category": category,
        "created_at": time.time(), "updated_at": time.time(),
    }
    if not configured():
        _LOCAL_COACH_NOTES[row["id"]] = row
        audit.record("coach_note_added", coach_user_id=coach_user_id, player_user_id=player_user_id,
                     category=category)
        return dict(row)
    supabase_row = {**row, "created_at": _to_iso(row["created_at"]), "updated_at": _to_iso(row["updated_at"])}
    get_service_client().table(COACH_NOTES_TABLE).insert(supabase_row).execute()
    audit.record("coach_note_added", coach_user_id=coach_user_id, player_user_id=player_user_id,
                 category=category)
    return row


def list_notes_by_coach_for_student(coach_user_id: str, player_user_id: str) -> list:
    """This one coach's notes for this one student - the coach's own
    per-student view. Newest first."""
    if not configured():
        rows = [r for r in _LOCAL_COACH_NOTES.values()
                if r["coach_user_id"] == coach_user_id and r["player_user_id"] == player_user_id]
    else:
        resp = (get_service_client().table(COACH_NOTES_TABLE).select("*")
                .eq("coach_user_id", coach_user_id).eq("player_user_id", player_user_id).execute())
        rows = resp.data or []
    return sorted(rows, key=lambda r: _parse_ts(r.get("created_at")), reverse=True)


def list_notes_about_player(player_user_id: str) -> list:
    """EVERY coach's notes about this player, across every coach who's ever
    added them - this is what the player's own dashboard reads (GET
    /account/coaching-notes) to close the loop: a player can always see
    what's been said about their play, from every coach, in one place -
    even a coach they've since removed from view on their side (see
    remove_student's docstring)."""
    if not configured():
        rows = [r for r in _LOCAL_COACH_NOTES.values() if r["player_user_id"] == player_user_id]
    else:
        resp = (get_service_client().table(COACH_NOTES_TABLE).select("*")
                .eq("player_user_id", player_user_id).execute())
        rows = resp.data or []
    return sorted(rows, key=lambda r: _parse_ts(r.get("created_at")), reverse=True)


def update_note(coach_user_id: str, note_id: str, **fields) -> Optional[dict]:
    """Only the coach who WROTE a note can edit it - scoped by both note_id
    and coach_user_id in the same query, same ownership-in-the-query-itself
    pattern as everywhere else in this module."""
    fields = dict(fields)
    fields["updated_at"] = time.time()
    if not configured():
        row = _LOCAL_COACH_NOTES.get(note_id)
        if row is None or row["coach_user_id"] != coach_user_id:
            return None
        row.update(fields)
        return dict(row)
    supabase_fields = {**fields, "updated_at": _to_iso(fields["updated_at"])}
    resp = (get_service_client().table(COACH_NOTES_TABLE).update(supabase_fields)
            .eq("id", note_id).eq("coach_user_id", coach_user_id).execute())
    return resp.data[0] if resp.data else None


def delete_note(coach_user_id: str, note_id: str) -> bool:
    if not configured():
        row = _LOCAL_COACH_NOTES.get(note_id)
        if row is None or row["coach_user_id"] != coach_user_id:
            return False
        del _LOCAL_COACH_NOTES[note_id]
        return True
    resp = (get_service_client().table(COACH_NOTES_TABLE).delete()
            .eq("id", note_id).eq("coach_user_id", coach_user_id).execute())
    return bool(resp.data)


# ------------------------------------------------------- playstyle profile --

def compute_playstyle_profile(user_id: str) -> dict:
    """The AGGREGATE-ONLY payload both GET /coach-view/{token} (public) and
    GET /coach/students/{player_id}/profile (authenticated coach) return -
    the exact same shape either way, so a coach sees identical data whether
    they're viewing through a fresh link or their own saved roster.

    Deliberately built ONLY from already-aggregate functions - record/report/
    skill-scores/skill-score-trend (see backend/analytics.py, backend/
    career.py) - never the raw merged event list, never compute_match_list
    (per-match rows), never decision_windows/strategic_analysis (per-turn
    detail). This was an explicit scope decision when the feature was built:
    a coach gets the same "coaching flags" / matchup-weakness / skill-trend
    picture the player's own Career tab shows, not a raw match browser and
    not video/reference-frame access - see this module's own top-of-file
    docstring for the full reasoning."""
    from . import analytics, career   # local import: avoids any import-order
                                        # coupling at module load time between
                                        # this newer module and the two it
                                        # composes over.

    merged, sessions = career.merge_user_events(user_id)
    return {
        "record": analytics.compute_record(merged),
        "report": analytics.compute_report(merged),
        "skill_scores": analytics.compute_skill_scores(merged),
        "skill_score_trend": career.compute_skill_score_trend(merged, sessions),
        "sessions_count": len(sessions),
        "generated_at": time.time(),
    }
