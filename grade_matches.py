"""
GRADING TOOL - turns "read terminal output and notice something's wrong" into
a structured, repeatable accuracy-grading pass (see ADDING_A_NEW_GAME.md step
5 and grade_accuracy.csv, which existed as a template but no real workflow to
fill it in).

For each match number you give it, this:
  1. Extracts the SAME roster-preview and result-screen frames analyze_matches.py
     actually used (same windows/resolution) into a review folder.
  2. Pulls what the system currently believes for that match (roster, brought,
     winner) straight from events.json.
  3. Writes/updates grade_accuracy.csv with one row per match, system's read
     already filled in, and blank columns for YOU to fill in after looking at
     the extracted frames (actual_roster, actual_winner, correct?, notes).

This doesn't grade anything itself - it can't watch the footage for you - but
it removes all the busywork around doing that grading pass, and gives you a
durable record of what was actually verified (vs. "I skimmed the terminal and
it looked fine").

Run, from poc-starter/:
  py grade_matches.py --video test.mp4 --matches 3,14,20,21
"""

import argparse
import csv
import json
import os
import sys

import analyze_matches as am


def load_events(path):
    if not os.path.exists(path):
        sys.exit(f"No {path} - run analyze_matches.py first.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_matches_csv(path):
    if not os.path.exists(path):
        sys.exit(f"No {path} - run structure_pass.py first.")
    with open(path, newline="", encoding="utf-8") as f:
        return {i: (float(r["start_seconds"]), float(r["end_seconds"]))
                for i, r in enumerate(csv.DictReader(f), 1)}


def system_read_for_match(events, match_num):
    tp = next((e for e in events if e.get("match") == match_num and e.get("event") == "team_preview"), {})
    be = next((e for e in events if e.get("match") == match_num and e.get("event") == "battle_end"), {})
    return {
        "player_team": tp.get("player_team", ""),
        "opponent_team": tp.get("opponent_team", ""),
        "player_brought": tp.get("player_brought", ""),
        "opponent_brought": tp.get("opponent_brought", ""),
        "illegal_species_detected": tp.get("illegal_species_detected", []),
        "winner": be.get("winner", "unknown"),
        "winner_detail": be.get("detail", ""),
    }


def extract_review_frames(ffmpeg, video, start, end, out_dir, hwaccel=""):
    """Same windows/resolution as analyze_matches.py's FIRST roster/winner
    attempts - not every retry window, just enough for a human to see what
    the model saw on its first try. Returns (roster_frame_count, result_frame_count)."""
    os.makedirs(out_dir, exist_ok=True)
    pre, dur, fps, cap = am.ROSTER_SEARCH_ATTEMPTS[0]
    roster_frames = am.sample_window(ffmpeg, video, max(0, start - pre), min(dur, start), fps,
                                      out_dir, "roster", hwaccel, scale_w=am.ROSTER_SCALE_W)
    pre, dur, fps, cap = am.WINNER_SEARCH_ATTEMPTS[0]
    result_frames = am.sample_window(ffmpeg, video, max(0, end - pre), dur, fps,
                                      out_dir, "result", hwaccel, scale_w=am.WINNER_SCALE_W)
    return len(roster_frames), len(result_frames)


def upsert_grade_rows(csv_path, rows):
    """rows: list of dicts with system_* fields filled in, actual_*/correct?/notes
    blank. Existing rows for a match number are replaced (re-grading), others
    are kept untouched."""
    fieldnames = ["match", "system_roster", "system_brought", "system_illegal",
                  "system_winner", "system_winner_detail",
                  "actual_roster", "actual_winner", "correct?", "notes"]
    existing = []
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames == fieldnames:   # only reuse if it's OUR format, not the old template
                existing = list(reader)

    # CSV rows always come back as strings (csv.DictReader), but freshly-built
    # rows carry an int match number - compare as strings on both sides so a
    # re-graded match's old row actually gets replaced instead of duplicated.
    new_matches = {str(r["match"]) for r in rows}
    kept = [r for r in existing if str(r.get("match")) not in new_matches]
    all_rows = kept + rows
    all_rows.sort(key=lambda r: int(r["match"]))

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(all_rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True)
    ap.add_argument("--matches", required=True, help="comma-separated match numbers to grade, e.g. 3,14,20,21")
    ap.add_argument("--events", default="events.json")
    ap.add_argument("--matches-csv", default="matches.csv")
    ap.add_argument("--out-dir", default="grading")
    ap.add_argument("--csv-out", default="grade_accuracy.csv")
    ap.add_argument("--hwaccel", default="", help="GPU decode, e.g. d3d11va")
    args = ap.parse_args()

    events = load_events(args.events)
    windows = load_matches_csv(args.matches_csv)
    match_nums = [int(x) for x in args.matches.split(",") if x.strip()]

    missing = [m for m in match_nums if m not in windows]
    if missing:
        sys.exit(f"Match number(s) not in {args.matches_csv}: {missing}")

    ffmpeg = am.find_ffmpeg()
    rows = []
    for m in match_nums:
        start, end = windows[m]
        sys_read = system_read_for_match(events, m)
        match_dir = os.path.join(args.out_dir, f"match_{m}")
        n_roster, n_result = extract_review_frames(ffmpeg, args.video, start, end, match_dir, args.hwaccel)

        print(f"Match {m} ({start:.0f}s-{end:.0f}s): extracted {n_roster} roster frames + "
              f"{n_result} result frames -> {match_dir}/")
        print(f"  system roster: player=[{sys_read['player_team']}]  opponent=[{sys_read['opponent_team']}]")
        print(f"  system brought: player=[{sys_read['player_brought']}]  opponent=[{sys_read['opponent_brought']}]")
        if sys_read["illegal_species_detected"]:
            print(f"  system rejected as illegal: {sys_read['illegal_species_detected']}")
        print(f"  system winner: {sys_read['winner']} ({sys_read['winner_detail']})")

        rows.append({
            "match": m,
            "system_roster": f"P1: {sys_read['player_team']} | P2: {sys_read['opponent_team']}",
            "system_brought": f"P1: {sys_read['player_brought']} | P2: {sys_read['opponent_brought']}",
            "system_illegal": ", ".join(sys_read["illegal_species_detected"]) or "",
            "system_winner": sys_read["winner"],
            "system_winner_detail": sys_read["winner_detail"],
            "actual_roster": "", "actual_winner": "", "correct?": "", "notes": "",
        })

    upsert_grade_rows(args.csv_out, rows)
    print(f"\nWrote/updated {len(rows)} row(s) in {args.csv_out}.")
    print(f"Next: open the JPGs under {args.out_dir}/match_<N>/ next to that row, and fill in "
          f"actual_roster / actual_winner / correct? / notes by hand.")


if __name__ == "__main__":
    main()
