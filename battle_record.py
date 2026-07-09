"""
STEP 4 - Win/loss record from the analyzed events.

This is your first real ANALYTICS step - no AI calls. It reads events.json
(from step 2) and works out the match record.

How it counts matches (doubles / Champions format):
  A 'team_preview' screen appears once per match, so team previews are the most
  reliable way to count matches. We split the event stream into matches at each
  team preview, then read the battle outcome (winner) inside each match.
  If no team previews were captured, we fall back to merging 'battle_end' markers.

Run it after step 2:
  py 4_battle_record.py
  py 4_battle_record.py --min-gap 120
"""

import argparse
import csv
import json
import os
import sys


def load_events(path):
    if path.endswith(".json") and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    csv_path = path if path.endswith(".csv") else "events.csv"
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    sys.exit(f"Couldn't find {path} (or events.csv). Run step 2 first.")


def _ts(e):
    try:
        return float(e.get("timestamp"))
    except (TypeError, ValueError):
        return 0.0


def event_is(e, name):
    return str(e.get("event", "")).strip() == name


def dedupe(events, min_gap):
    """Collapse events of the same kind that fire within min_gap seconds into one."""
    kept = []
    for e in sorted(events, key=_ts):
        if kept and (_ts(e) - _ts(kept[-1])) < min_gap:
            kept[-1] = e
        else:
            kept.append(e)
    return kept


def decide_winner(ev):
    """Who won, from a battle_end event, as robustly as possible."""
    w = str(ev.get("winner") or "").strip().lower()
    if w in ("player", "opponent"):
        return w
    text = f"{ev.get('detail','')} {ev.get('actor','')}".lower()
    if any(x in text for x in ["you won", "you win", "victory", "player won", "defeated the opponent"]):
        return "player"
    if any(x in text for x in ["you lost", "you were defeated", "you whited out", "you blacked out",
                               "opponent won", "player lost", "defeat"]):
        return "opponent"
    actor = str(ev.get("actor") or "").strip().lower()
    return actor if actor in ("player", "opponent") else "unknown"


def matches_from_previews(events, previews, ends):
    """Split into matches at each team preview; outcome = the last battle_end inside each."""
    pts = [_ts(p) for p in previews]
    out = []
    for i, start in enumerate(pts):
        stop = pts[i + 1] if i + 1 < len(pts) else float("inf")
        seg_ends = sorted([e for e in ends if start <= _ts(e) < stop], key=_ts)
        if seg_ends:
            end = seg_ends[-1]                      # the real end-of-match screen
            out.append({"timestamp": end.get("timestamp"), "winner": decide_winner(end),
                        "detail": end.get("detail", "")})
        else:
            out.append({"timestamp": round(start, 1), "winner": "unknown",
                        "detail": "(no end-of-match screen captured)"})
    return out


def main():
    ap = argparse.ArgumentParser(description="Tally win/loss record from analyzed events.")
    ap.add_argument("--events", default="events.json", help="Events file from step 2")
    ap.add_argument("--out", default="battle_record.csv", help="Where to write the per-match record")
    ap.add_argument("--min-gap", type=float, default=90.0,
                    help="Seconds; duplicate team_preview/battle_end markers closer than this are merged (default 90)")
    args = ap.parse_args()

    events = load_events(args.events)
    previews = dedupe([e for e in events if event_is(e, "team_preview")], args.min_gap)
    ends = [e for e in events if event_is(e, "battle_end")]

    if previews:
        results = matches_from_previews(events, previews, ends)
        match_count = len(previews)
        method = "team previews (one per match)"
    else:
        merged = dedupe(ends, max(args.min_gap, 150))   # fallback: merge battle-end markers
        results = [{"timestamp": e.get("timestamp"), "winner": decide_winner(e),
                    "detail": e.get("detail", "")} for e in merged]
        match_count = len(merged)
        method = "battle-end markers (no team previews were captured)"

    wins = sum(1 for r in results if r["winner"] == "player")
    losses = sum(1 for r in results if r["winner"] == "opponent")
    unknown = sum(1 for r in results if r["winner"] not in ("player", "opponent"))

    player_faints = sum(1 for e in events if event_is(e, "pokemon_fainted")
                        and str(e.get("actor", "")).lower() == "player")
    opp_faints = sum(1 for e in events if event_is(e, "pokemon_fainted")
                     and str(e.get("actor", "")).lower() == "opponent")

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "winner", "detail"])
        writer.writeheader()
        writer.writerows(results)

    decided = wins + losses
    print("================  BATTLE RECORD  ================")
    print(f"Matches counted:    {match_count}   (via {method})")
    print(f"  Wins:             {wins}")
    print(f"  Losses:           {losses}")
    if unknown:
        print(f"  Undetermined:     {unknown}  (outcome not clearly captured)")
    if decided:
        print(f"\n  Record:           {wins}-{losses}")
        print(f"  Win rate:         {wins/decided*100:.1f}%")
    print(f"\nCross-check — Pokemon fainted:  player {player_faints}  |  opponent {opp_faints}")
    print("=================================================")
    print(f"\nWrote per-match list to {args.out}")

    if match_count == 0:
        print("\nNo matches found. Re-run step 2 (the schema now understands doubles + team preview),")
        print("or re-extract with a lower --threshold so the team-preview screens are captured.")


if __name__ == "__main__":
    main()
