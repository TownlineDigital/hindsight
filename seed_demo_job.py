"""
Copy the pipeline outputs already sitting in this folder (events.json,
matches.csv, etc. - from a prior manual `py run_full.py` run) into
jobs/demo/, and register it as a real job owned by YOUR account in the
`jobs` Postgres table (see supabase_schema.sql).

Jobs are no longer auto-discovered from disk on server startup - every job
needs an owner now (see backend/jobs.py), so this script also does the
one-time "attach this folder to my account" step that used to happen for
free.

Run once, from poc-starter/, AFTER you've signed up at least once in the
frontend's login screen (so you have a real Supabase user id). Find your
user id in the Supabase dashboard: Authentication -> Users -> copy the "UID"
column for your account.

  py seed_demo_job.py --user-id <your-supabase-user-uuid>

Then start the backend (see backend/README_BACKEND.md) - job "demo" will
show up in your account's job list and the dashboard will show it.
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
DEMO_DIR = HERE / "jobs" / "demo"

FILES = ["events.json", "events.csv", "matches.csv", "battle_record.csv",
         "player_report.md", "coach_report.md", "schema.json", "transcript.json"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user-id", required=True,
                    help="Your Supabase user UUID (Authentication -> Users in the Supabase dashboard)")
    args = ap.parse_args()

    load_dotenv(HERE / ".env")
    supabase_url = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set - copy .env.example to .env "
                  "and fill them in first (see backend/README_BACKEND.md 'Accounts').")

    try:
        from supabase import create_client
    except ImportError:
        sys.exit("Run: pip install supabase")

    sys.path.insert(0, str(HERE))
    from backend.pipeline import TOTAL_STEPS

    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    copied, skipped = [], []
    for name in FILES:
        src = HERE / name
        if src.exists():
            shutil.copy2(src, DEMO_DIR / name)
            copied.append(name)
        else:
            skipped.append(name)

    print(f"Seeded jobs/demo/ from {HERE}")
    print(f"  copied:  {', '.join(copied) or '(none)'}")
    if skipped:
        print(f"  not found (skipped): {', '.join(skipped)}")
    if "events.json" not in copied:
        print("\n  WARNING: events.json wasn't found - the dashboard needs this one. "
              "Run the pipeline first (py run_full.py ...) or point this script at "
              "the right folder.")
        return

    client = create_client(supabase_url, service_key)
    row = {
        "job_id": "demo", "user_id": args.user_id, "dir": str(DEMO_DIR),
        "status": "done", "step": "done", "step_index": TOTAL_STEPS, "total_steps": TOTAL_STEPS,
        "game": "pokemon", "mode": "doubles", "source_type": "seed",
    }
    client.table("jobs").upsert(row).execute()
    print(f"\nRegistered job 'demo' for user {args.user_id}.")
    print("Start the backend and open http://127.0.0.1:8000/dashboard/")


if __name__ == "__main__":
    main()
