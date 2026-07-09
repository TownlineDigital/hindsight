"""
Auth verification - reads the Supabase session token the frontend attaches as
`Authorization: Bearer <access_token>` (set on sign-in via supabase-js, see
frontend/src/lib/supabase.js) and resolves it to a real user by asking
Supabase's own Auth server. This backend never handles passwords, sessions,
or token issuance itself - Supabase Auth owns all of that; this file's only
job is "given a token, whose request is this," so the rest of the backend
(jobs.py, main.py) can scope data by user_id.

Uses the SERVICE ROLE key (server-side only, never sent to the frontend) -
that key can validate any user's token and bypasses Row Level Security, which
is why every function in jobs.py filters by user_id explicitly in the query
itself rather than relying on RLS to do it implicitly.

LOCAL DEV MODE: if SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY aren't set at all
(no .env filled in yet), current_user() returns a fixed local user instead of
requiring a real session - this is what lets you run the app and check the
dashboard with zero cloud setup, exactly like before accounts existed. The
moment real Supabase credentials ARE set, this same code requires a real
signed-in session again - there's no separate flag to remember to flip back.
jobs.py has a matching local-mode fallback (see LOCAL_USER_ID there).
"""

import os

from fastapi import Header, HTTPException
from supabase import Client, create_client

_SUPABASE_URL = os.environ.get("SUPABASE_URL")
_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

_client: Client | None = None

LOCAL_USER = {"id": "local-dev", "email": "local@dev"}


def configured() -> bool:
    """Whether Supabase env vars are actually set. False means the app runs
    in single-user local dev mode (see LOCAL_USER above and jobs.py) instead
    of requiring real accounts - not a special "test flag," just what happens
    when .env hasn't been filled in yet."""
    return bool(_SUPABASE_URL and _SERVICE_KEY)


def get_service_client() -> Client:
    """The one Supabase client the whole backend uses - service_role key, so
    it can read/write any row (application code enforces ownership, not RLS).
    Shared/cached across requests rather than reconnecting every call."""
    global _client
    if _client is None:
        if not configured():
            raise HTTPException(
                500,
                "Supabase is not configured on the server. Copy .env.example to .env "
                "and fill in SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY - see "
                "backend/README_BACKEND.md 'Accounts'.",
            )
        _client = create_client(_SUPABASE_URL, _SERVICE_KEY)
    return _client


def current_user(authorization: str = Header(default="")) -> dict:
    """FastAPI dependency - add `user: dict = Depends(current_user)` to any
    endpoint that needs to know who's calling. Raises 401 if the token is
    missing, malformed, or no longer valid (expired/signed out) - UNLESS
    Supabase isn't configured at all, in which case every request is treated
    as LOCAL_USER (see module docstring)."""
    if not configured():
        return LOCAL_USER
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or malformed Authorization header (expected 'Bearer <token>'). "
                                  "Sign in first - see frontend's login screen.")
    token = authorization[len("Bearer "):].strip()
    if not token:
        raise HTTPException(401, "Empty bearer token.")

    client = get_service_client()
    try:
        resp = client.auth.get_user(token)
    except Exception as e:
        raise HTTPException(401, f"Invalid or expired session: {str(e)[:200]}")

    user = getattr(resp, "user", None)
    if not user:
        raise HTTPException(401, "Invalid or expired session.")
    return {"id": user.id, "email": user.email}
