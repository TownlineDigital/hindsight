"""
STEP 5 - Player performance report from the structured events.

No AI calls - this just aggregates events.json (from step 2) into a readable
report about how the player did: record, KO differential, most-used Pokemon and
moves, Tera usage. Writes player_report.md and prints a summary.

Run after step 2:
  py player_report.py
"""

import argparse
import json
import os
import sys
from collections import Counter


def load_events(path):
    if path.endswith(".json") and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    csv_path = path if path.endswith(".csv") else "events.csv"
    if os.path.exists(csv_path):
        import csv
        with open(csv_path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    sys.exit(f"Couldn't find {path} (or events.csv). Run step 2 first.")


def _ts(e):
    try:
        return float(e.get("timestamp"))
    except (TypeError, ValueError):
        return 0.0


def is_(e, name):
    return str(e.get("event", "")).strip() == name


def actor_of(e):
    return str(e.get("actor", "")).strip().lower()


def dedupe(events, gap):
    kept = []
    for e in sorted(events, key=_ts):
        if kept and (_ts(e) - _ts(kept[-1])) < gap:
            kept[-1] = e
        else:
            kept.append(e)
    return kept


def decide_winner(ev):
    w = str(ev.get("winner") or "").strip().lower()
    if w in ("player", "opponent"):
        return w
    text = f"{ev.get('detail','')} {ev.get('actor','')}".lower()
    if any(x in text for x in ["you won", "victory", "player won"]):
        return "player"
    if any(x in text for x in ["you lost", "defeat", "opponent won"]):
        return "opponent"
    a = actor_of(ev)
    return a if a in ("player", "opponent") else "unknown"


def record_from_previews(events, gap):
    previews = dedupe([e for e in events if is_(e, "team_preview")], gap)
    ends = [e for e in events if is_(e, "battle_end")]
    if not previews:
        ends = dedupe(ends, max(gap, 150))
        outcomes = [decide_winner(e) for e in ends]
        return len(ends), outcomes
    pts = [_ts(p) for p in previews]
    outcomes = []
    for i, start in enumerate(pts):
        stop = pts[i + 1] if i + 1 < len(pts) else float("inf")
        seg = sorted([e for e in ends if start <= _ts(e) < stop], key=_ts)
        outcomes.append(decide_winner(seg[-1]) if seg else "unknown")
    return len(previews), outcomes


def top(counter, n=5):
    return counter.most_common(n)


def names_of(value):
    """Return a clean list of Pokemon names from whatever shape the AI returned:
    a comma-string ("A, B"), a list of strings, or a list of dicts ({"pokemon": "A", ...}).
    Matches analyze_matches.py's helper of the same name - keeps richer field_state
    formats (list of {"pokemon", "hp_percent"} dicts) from garbling this count."""
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


def main():
    ap = argparse.ArgumentParser(description="Build a player performance report from events.")
    ap.add_argument("--events", default="events.json")
    ap.add_argument("--out", default="player_report.md")
    ap.add_argument("--min-gap", type=float, default=90.0)
    args = ap.parse_args()

    events = load_events(args.events)

    matches, outcomes = record_from_previews(events, args.min_gap)
    wins = outcomes.count("player")
    losses = outcomes.count("opponent")
    decided = wins + losses
    win_rate = (wins / decided * 100) if decided else 0.0

    moves = Counter()
    mons_by_move = Counter()
    field_mons = Counter()
    tera_player = 0
    for e in events:
        a = actor_of(e)
        if is_(e, "move_used") and a == "player":
            if e.get("detail"):
                moves[str(e["detail"]).strip()] += 1
            if e.get("pokemon"):
                mons_by_move[str(e["pokemon"]).strip()] += 1
        if is_(e, "field_state") and e.get("player_active"):
            for name in names_of(e["player_active"]):
                field_mons[name] += 1
        if is_(e, "terastallized") and a == "player":
            tera_player += 1

    player_faints = sum(1 for e in events if is_(e, "pokemon_fainted") and actor_of(e) == "player")
    opp_faints = sum(1 for e in events if is_(e, "pokemon_fainted") and actor_of(e) == "opponent")

    brought = Counter()
    leads = Counter()
    for e in events:
        if is_(e, "team_preview"):
            for nm in str(e.get("player_brought", "")).split(","):
                if nm.strip():
                    brought[nm.strip()] += 1
            for nm in str(e.get("player_lead", "")).split(","):
                if nm.strip():
                    leads[nm.strip()] += 1

    # ---- write the report ----
    lines = []
    lines.append("# Player Performance Report\n")
    lines.append("## Record")
    lines.append(f"- Matches: **{matches}**")
    lines.append(f"- Record: **{wins}-{losses}**" + (f"  ({win_rate:.0f}% win rate)" if decided else ""))
    if outcomes.count("unknown"):
        lines.append(f"- Undetermined outcomes: {outcomes.count('unknown')}")
    lines.append("")
    lines.append("## Combat")
    lines.append(f"- KOs landed (opponent Pokémon fainted): **{opp_faints}**")
    lines.append(f"- Pokémon lost (your Pokémon fainted): **{player_faints}**")
    diff = opp_faints - player_faints
    lines.append(f"- KO differential: **{'+' if diff >= 0 else ''}{diff}**")
    lines.append(f"- Terastallizations used: **{tera_player}**")
    lines.append("")
    lines.append("## Most-used Pokémon (by moves made)")
    for name, c in top(mons_by_move):
        lines.append(f"- {name}: {c}")
    if not mons_by_move:
        lines.append("- (none detected)")
    lines.append("")
    lines.append("## Most-seen Pokémon (time on field)")
    for name, c in top(field_mons):
        lines.append(f"- {name}: {c} frames")
    if not field_mons:
        lines.append("- (none detected)")
    lines.append("")
    lines.append("## Most-brought Pokémon (chosen in team preview)")
    for name, c in top(brought):
        lines.append(f"- {name}: brought in {c} matches")
    if not brought:
        lines.append("- (none detected)")
    lines.append("")
    lines.append("## Most common leads")
    for name, c in top(leads):
        lines.append(f"- {name}: {c}")
    if not leads:
        lines.append("- (none detected)")
    lines.append("")
    lines.append("## Most-used moves")
    for name, c in top(moves, 8):
        lines.append(f"- {name}: {c}")
    if not moves:
        lines.append("- (none detected)")
    lines.append("")

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # ---- console summary ----
    print("===============  PLAYER REPORT  ===============")
    print(f"Record:          {wins}-{losses}" + (f"  ({win_rate:.0f}% win rate)" if decided else ""))
    print(f"KOs landed:      {opp_faints}   |   Pokémon lost: {player_faints}   (diff {'+' if diff>=0 else ''}{diff})")
    print(f"Teras used:      {tera_player}")
    if brought:
        print("Most brought:    " + ", ".join(f"{n} ({c})" for n, c in top(brought, 3)))
    if mons_by_move:
        print("Top Pokémon:     " + ", ".join(f"{n} ({c})" for n, c in top(mons_by_move, 3)))
    if moves:
        print("Top moves:       " + ", ".join(f"{n} ({c})" for n, c in top(moves, 3)))
    print("===============================================")
    print(f"\nFull report written to {args.out}")


if __name__ == "__main__":
    main()
