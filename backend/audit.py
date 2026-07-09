"""
INTERNAL AUDIT LOG - a durable record of what got submitted and what happened
to it, kept separately from any single job's own folder so it survives even
if a job folder or its metadata row were ever removed. This is for internal
review (debugging accuracy issues, understanding real usage over time) - it
is NOT exposed through any API endpoint, so end users never see it.

Two storage targets, used together whenever Supabase is configured:

  1. LOCAL FILE (always): one JSON line per event, appended to
     `audit_log.jsonl` at the project root (gitignored - see .gitignore).
     This is what makes the log durable even before/without any cloud setup,
     and is the only target used in local dev mode.
  2. SUPABASE TABLE `audit_log` (only when configured() is true): a proper
     queryable table, service-role-write-only - see supabase_schema.sql's
     RLS setup for that table (no select/insert policy for regular users at
     all, so a leaked anon key could never read or forge entries).

Every record is freeform ({event_type, created_at, payload: {...}}) rather
than a fixed schema, so a new kind of event to track never needs a
migration - just call record() with whatever fields make sense for it.

Deliberately fails soft: any error writing an audit entry is caught and
logged to stderr, never raised - "the internal log line didn't get written"
must never be the reason a real user-facing job fails.
"""

import json
import sys
import time
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent   # poc-starter/
LOG_PATH = BASE_DIR / "audit_log.jsonl"

TABLE = "audit_log"


def record(event_type: str, **fields) -> None:
    """Append one audit record. event_type examples: "job_created",
    "job_step", "job_completed", "job_failed", "event_corrected". Every
    keyword arg becomes part of the record's freeform `payload` - callers
    pass whatever's relevant (job_id, user_id, source_type, before/after
    values for a correction, ...)."""
    entry = {"id": uuid.uuid4().hex[:12], "event_type": event_type,
             "created_at": time.time(), "payload": fields}

    try:
        _write_local(entry)
    except Exception as e:
        print(f"[audit] failed to write local log: {e}", file=sys.stderr)

    try:
        from .auth import configured, get_service_client   # local import - avoids
                                                             # a module-load-time
                                                             # dependency cycle
        if configured():
            get_service_client().table(TABLE).insert(entry).execute()
    except Exception as e:
        print(f"[audit] failed to write to Supabase: {e}", file=sys.stderr)


def _write_local(entry: dict) -> None:
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def read_local(limit: int = 200) -> list:
    """Returns the most recent `limit` local audit entries, oldest-to-newest -
    a convenience for a developer inspecting audit_log.jsonl directly (e.g.
    via `python -c "from backend import audit; print(audit.read_local())"`),
    NOT wired into any API endpoint."""
    if not LOG_PATH.exists():
        return []
    lines = LOG_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
