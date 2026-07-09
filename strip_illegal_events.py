"""
Remove events from an events.json that are impossible under the CURRENT
format rules (schema.json's event_types, after a fresh `py compose_schema.py`).

Why this exists: adapters/pokemon/doubles.json has removed "terastallized"
(this format has no Terastallization - see its "rules" block), but the
schema.json this events.json was extracted with was stale - it hadn't been
recomposed after that adapter edit (a known gotcha, see
ARCHITECTURE_HANDOFF.md section 6). So the AI was still told Tera was a valid
event type to look for, and reported a few. This strips any event whose
"event" type isn't in the freshly-composed schema - generalizes beyond just
Tera if the adapters change again later. Writes a .bak backup first.

Run, from poc-starter/ (after `py compose_schema.py --game pokemon --mode doubles`):
  py strip_illegal_events.py
  py strip_illegal_events.py --events jobs/demo/events.json
"""

import argparse
import json
import shutil


def main():
    ap = argparse.ArgumentParser(description="Strip events whose type isn't legal under the current schema.")
    ap.add_argument("--events", default="events.json")
    ap.add_argument("--schema", default="schema.json")
    args = ap.parse_args()

    with open(args.schema, encoding="utf-8") as f:
        schema = json.load(f)
    allowed = set(schema.get("event_types", []))

    shutil.copy2(args.events, args.events + ".bak")
    with open(args.events, encoding="utf-8") as f:
        events = json.load(f)

    kept, dropped = [], []
    for e in events:
        if e.get("event") in allowed:
            kept.append(e)
        else:
            dropped.append(e)

    with open(args.events, "w", encoding="utf-8") as f:
        json.dump(kept, f, indent=2)

    print(f"{args.events}: kept {len(kept)}, dropped {len(dropped)} illegal event(s)")
    for e in dropped:
        print(f"  dropped: match {e.get('match')} @ {e.get('timestamp')}s -> "
              f"{e.get('event')} ({e.get('pokemon', '')})")
    print(f"Backup saved to {args.events}.bak")


if __name__ == "__main__":
    main()
