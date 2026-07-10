"""
Long-lived API keys - lets an external client (the planned Pokemon Showdown
browser extension, or any other future integration) authenticate to this
backend WITHOUT a short-lived Supabase session token. A content script /
background service worker running on replay.pokemonshowdown.com has no way
to read this dashboard's Supabase session (different origin, and Supabase
sessions expire/refresh on their own schedule anyway) - a key the player
generates once from their own dashboard and pastes into the extension's
settings solves that, at the cost of "this credential doesn't expire on its
own until you revoke it," which is why it's a deliberately separate,
narrower mechanism from normal sign-in rather than a replacement for it.

KEY FORMAT: "vgc_" + secrets.token_urlsafe(32). The "vgc_" prefix isn't
decorative - backend/auth.py's current_user() branches on it to decide
whether a bearer token should be checked against THIS module or handed to
Supabase's auth.get_user() as a session JWT, without needing a network round
trip just to find out which kind of token it is.

STORAGE: only a SHA-256 hash of each key is ever stored (key_hash below) -
never the plaintext. The plaintext is shown to the player exactly once, in
the response to create_api_key(), and never again after that (list_api_keys
only ever returns key_prefix, the first 12 characters, so the player can
still tell keys apart in their own list without this backend being able to
leak a usable credential even if the database itself were ever read by
someone else). This mirrors how you'd treat a password, not how
share_links.token is handled (that one IS the access control and is looked
up by exact value on every public read, but a share link is meant to be
handed to someone else - an API key is meant to stay secret to one client).

LOCAL DEV MODE (see backend/auth.py's configured()): falls back to a
module-level in-memory dict, same pattern as backend/coaching.py. Local dev
mode's auth.current_user() always returns LOCAL_USER regardless of what
Authorization header (if any) is sent, so a locally-created key isn't
actually required to authenticate anything there - but create/list/revoke
still work end to end, same "exercise every code path without crashing"
reasoning as coaching.py's local mode.
"""

import hashlib
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from . import audit
from .auth import configured, get_service_client

API_KEYS_TABLE = "api_keys"
KEY_PREFIX = "vgc_"

# ---- local dev mode (no Supabase configured) --------------------------------
_LOCAL_API_KEYS: dict = {}   # key_hash -> row
# ------------------------------------------------------------------------------


def _parse_ts(value) -> float:
    """Same dual-shape normalization as coaching.py's _parse_ts - local dev
    mode stores plain float unix seconds, real Supabase returns an ISO-8601
    string for any timestamptz column."""
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
    """The other direction of _parse_ts - see coaching.py's _to_iso for why
    this conversion exists (Postgres timestamptz can't parse a raw unix-
    seconds float)."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _new_id() -> str:
    return secrets.token_hex(12)


def _hash(plaintext_key: str) -> str:
    return hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()


def looks_like_api_key(token: str) -> bool:
    """Cheap prefix check backend/auth.py's current_user() uses to decide
    whether a bearer token should be resolved here or handed to Supabase as
    a session JWT - avoids a wasted network call to Supabase for tokens that
    were never going to be a valid session anyway."""
    return token.startswith(KEY_PREFIX)


def create_api_key(user_id: str, label: Optional[str] = None) -> dict:
    """Generates a new key and returns it WITH the plaintext `key` field -
    the only time this backend ever returns or holds the plaintext again
    after this call returns, only key_hash is stored. `label` is the
    player's own private note about what this key is for (e.g. "Showdown
    extension - laptop"), same idea as share_links.label."""
    plaintext = KEY_PREFIX + secrets.token_urlsafe(32)
    now = time.time()
    row = {
        "id": _new_id(), "user_id": user_id, "label": label,
        "key_hash": _hash(plaintext), "key_prefix": plaintext[:12],
        "created_at": now, "last_used_at": None, "revoked_at": None,
    }
    if not configured():
        _LOCAL_API_KEYS[row["key_hash"]] = row
        audit.record("api_key_created", user_id=user_id, key_id=row["id"], label=label)
        return {**row, "key": plaintext}
    supabase_row = {**row, "created_at": _to_iso(now)}
    get_service_client().table(API_KEYS_TABLE).insert(supabase_row).execute()
    audit.record("api_key_created", user_id=user_id, key_id=row["id"], label=label)
    return {**row, "key": plaintext}


def list_api_keys(user_id: str) -> list:
    """This player's keys, metadata only (never key_hash, never anything the
    plaintext could be reconstructed from) - active, and already-revoked
    ones too, so the player's own management view can show "this one I
    already turned off" apart from "this one's still live", same convention
    as coaching.list_share_links."""
    if not configured():
        rows = [r for r in _LOCAL_API_KEYS.values() if r["user_id"] == user_id]
    else:
        resp = (get_service_client().table(API_KEYS_TABLE).select("*")
                .eq("user_id", user_id).execute())
        rows = resp.data or []
    rows = sorted(rows, key=lambda r: _parse_ts(r.get("created_at")), reverse=True)
    return [{k: v for k, v in r.items() if k != "key_hash"} for r in rows]


def revoke_api_key(user_id: str, key_id: str) -> bool:
    """Immediately and permanently disables a key - resolve_api_key() checks
    revoked_at on every lookup, so an already-running extension stops
    authenticating on its NEXT request, not retroactively (there's no
    session to invalidate, since a key is checked fresh every call rather
    than exchanged for a session)."""
    if not configured():
        row = _LOCAL_API_KEYS.get(key_id) if key_id in _LOCAL_API_KEYS else None
        # local dict is keyed by key_hash, not id - fall back to a scan (fine
        # at local-dev scale, and keeps this function's signature the same
        # shape as the Supabase branch)
        row = next((r for r in _LOCAL_API_KEYS.values()
                    if r["id"] == key_id and r["user_id"] == user_id), None)
        if row is None:
            return False
        row["revoked_at"] = time.time()
        audit.record("api_key_revoked", user_id=user_id, key_id=key_id)
        return True
    resp = (get_service_client().table(API_KEYS_TABLE)
            .update({"revoked_at": _to_iso(time.time())})
            .eq("id", key_id).eq("user_id", user_id).execute())
    ok = bool(resp.data)
    if ok:
        audit.record("api_key_revoked", user_id=user_id, key_id=key_id)
    return ok


def resolve_api_key(plaintext_key: str) -> Optional[dict]:
    """The one function backend/auth.py's current_user() calls to answer "is
    this key currently valid, and whose request is this." Returns
    {"id", "email"} (matching the shape current_user() already returns for a
    Supabase-JWT-resolved user) or None - collapsing "key never existed" and
    "key was revoked" into the same result, same "don't tell an attacker
    which" principle as coaching.resolve_share_link. Best-effort updates
    last_used_at (swallow-on-failure - a broken analytics timestamp should
    never be the reason a real authenticated request fails)."""
    key_hash = _hash(plaintext_key)
    if not configured():
        row = _LOCAL_API_KEYS.get(key_hash)
    else:
        resp = (get_service_client().table(API_KEYS_TABLE).select("*")
                .eq("key_hash", key_hash).limit(1).execute())
        row = resp.data[0] if resp.data else None
    if row is None or row.get("revoked_at"):
        return None
    try:
        now = time.time()
        if not configured():
            row["last_used_at"] = now
        else:
            get_service_client().table(API_KEYS_TABLE).update(
                {"last_used_at": _to_iso(now)}).eq("key_hash", key_hash).execute()
    except Exception:
        pass
    # API keys have no separate account email of their own to resolve here
    # (this app has no general "look up any account's email by user_id"
    # capability - see coaching.add_note's docstring for the same tradeoff)
    # - callers that need it already have user_id and can look elsewhere if
    # they ever need to.
    return {"id": row["user_id"], "email": None}
