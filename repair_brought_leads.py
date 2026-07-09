"""
One-time repair for events.json files written before analyze_matches.py's
derive_brought() was fixed to handle the richer field_state shape (a list of
{"pokemon": ..., "hp_percent": ...} dicts, instead of a plain comma-string of
names). The old code did str(that_list).split(",") and picked up fragments
like "'hp_percent': 100}" as if they were Pokemon names - that's the garbage
you see in player_brought / player_lead / the win-rate-by-lead table on older
events.json files.

This does NOT need the video or Gemini again. The per-turn field_state events
already have the correct data (a real list of dicts) - only the DERIVED
summary written onto each match's team_preview event was garbled. This script
re-derives that summary from the events already on disk and overwrites it in
place. Writes a events.json.bak backup first.

Run, from poc-starter/:
  py repair_brought_leads.py                        (fixes ./events.json)
  py repair_brought_leads.py --events jobs/demo/events.json
"""

import argparse
import json
import re
import shutil
from collections import defaultdict


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _canon(name, name_map):
    """Match an event's Pokemon name to the known roster (exact, then light fuzzy).
    Mirrors analyze_matches.py's _canon()."""
    key = _norm(name)
    if key in name_map:
        return name_map[key]
    for k, v in name_map.items():
        if k and (k.startswith(key) or key.startswith(k) or key in k or k in key):
            return v
    return str(name).strip()


def names_of(value):
    """Return a clean list of Pokemon names from whatever shape the AI returned:
    a comma-string ("A, B"), a list of strings, or a list of dicts ({"pokemon": "A", ...}).
    Mirrors analyze_matches.py's names_of() - the fixed version."""
    if value is None:
        return []
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    if isinstance(value, dict):
        n = value.get("name") or value.get("pokemon") or value.get("species")
        return [str(n).strip()] if n else []
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict):
                n = item.get("name") or item.get("pokemon") or item.get("species")
                if n:
                    out.append(str(n).strip())
        return out
    return [str(value).strip()]


def ts(e):
    try:
        return float(e.get("timestamp"))
    except (TypeError, ValueError):
        return 0.0


SINGLE = {"move_used", "pokemon_sent_out", "pokemon_fainted", "terastallized",
          "hp_change", "status_inflicted", "item_or_ability_activated"}


def recompute_brought(match_events, pteam, oteam):
    """Same algorithm as analyze_matches.py's derive_brought(), just re-run
    against events already on disk instead of live during extraction."""
    pmap = {_norm(n): n for n in pteam}
    omap = {_norm(n): n for n in oteam}
    p_seen, o_seen = [], []
    for e in sorted(match_events, key=ts):
        ev = str(e.get("event", ""))
        side = str(e.get("actor", "")).lower()
        pairs = []
        if ev in SINGLE and e.get("pokemon"):
            for nm in names_of(e.get("pokemon")):
                pairs.append((side, nm))
        if ev == "field_state":
            for nm in names_of(e.get("player_active")):
                pairs.append(("player", nm))
            for nm in names_of(e.get("opponent_active")):
                pairs.append(("opponent", nm))
        for s, nm in pairs:
            if s == "player":
                c = _canon(nm, pmap) if pmap else nm.strip()
                if c and c not in p_seen:
                    p_seen.append(c)
            elif s == "opponent":
                c = _canon(nm, omap) if omap else nm.strip()
                if c and c not in o_seen:
                    o_seen.append(c)
    return p_seen[:4], o_seen[:4], p_seen[:2], o_seen[:2]


def main():
    ap = argparse.ArgumentParser(description="Repair garbled player_brought/player_lead in an existing events.json.")
    ap.add_argument("--events", default="events.json")
    args = ap.parse_args()

    shutil.copy2(args.events, args.events + ".bak")

    with open(args.events, encoding="utf-8") as f:
        events = json.load(f)

    by_match = defaultdict(list)
    for e in events:
        if e.get("match") is not None:
            by_match[e["match"]].append(e)

    fixed = 0
    for m, evs in by_match.items():
        tp = next((e for e in evs if e.get("event") == "team_preview"), None)
        if not tp:
            continue
        pteam = [x.strip() for x in str(tp.get("player_team", "")).split(",") if x.strip()]
        oteam = [x.strip() for x in str(tp.get("opponent_team", "")).split(",") if x.strip()]
        pbrought, obrought, plead, olead = recompute_brought(evs, pteam, oteam)

        before = (tp.get("player_brought"), tp.get("player_lead"))
        tp["player_brought"] = ", ".join(pbrought)
        tp["opponent_brought"] = ", ".join(obrought)
        tp["player_lead"] = ", ".join(plead)
        tp["opponent_lead"] = ", ".join(olead)
        tp["detail"] = (f"P1 team: {', '.join(pteam)} | P2 team: {', '.join(oteam)}  ||  "
                        f"P1 brought: {', '.join(pbrought)} | P2 brought: {', '.join(obrought)}")
        if (tp.get("player_brought"), tp.get("player_lead")) != before:
            fixed += 1

    with open(args.events, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2)

    print(f"Repaired {fixed}/{len(by_match)} matches' brought/lead fields in {args.events}")
    print(f"Backup of the original saved to {args.events}.bak")


if __name__ == "__main__":
    main()
