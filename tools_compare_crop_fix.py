"""
Live comparison: does the opponent-icon-column crop (analyze_matches.
crop_opponent_icon_column, wired into read_roster) actually change the roster
read on the two real matches that motivated it?

  - Match 2 (starts 620.0s in jobs/303d13ba0940/vod.mp4): human-confirmed the
    opponent brought Whimsicott + Kommo-o, but the OLD roster read missed
    both, causing later events to get silently swapped to Amoonguss/Dragonite.
  - Match 4 (starts 1980.0s): human-confirmed (via literal on-screen text,
    "The opposing Kingambit fainted!") the opponent had Kingambit, but the
    OLD roster read missed it, causing events to get swapped to Bisharp.

Runs each condition (old/new) REPEATS times per match rather than once, and
reports a hit-RATE instead of a single yes/no. This was added after real runs
showed match 4's OLD (no-crop) result isn't stable across repeats even with
temperature=0.1 (Kingambit appeared once, then was missing on two later
reruns) - a single A/B sample can't tell a genuine regression apart from
ordinary API-side variance, so this needs several samples per condition to
mean anything. Each repeat is a REAL Gemini call, so total cost scales with
REPEATS (default 3 -> 12 calls total: 2 matches x 2 conditions x 3 repeats) -
still small money, but worth knowing before running a larger REPEATS value.

This must be run somewhere with real internet access to
generativelanguage.googleapis.com (e.g. your own machine, wherever the
dashboard's backend normally runs) - it will NOT work from a restricted
sandbox that blocks that host.

Usage (from poc-starter/, with GEMINI_API_KEY set in .env or the environment):
    py tools_compare_crop_fix.py              (3 repeats per condition)
    py tools_compare_crop_fix.py --repeats 5
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import analyze_matches as am

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from google import genai

JOB_DIR = os.path.join("jobs", "303d13ba0940")
VIDEO = os.path.join(JOB_DIR, "vod.mp4")
WORKDIR_BASE = os.path.join(JOB_DIR, "_crop_fix_livetest")

# (match label, start_seconds, species we expect to now show up in
#  opponent_team that the OLD roster read missed)
CASES = [
    ("match 2 (Whimsicott/Kommo-o)", 620.0, ["Whimsicott", "Kommo-o"]),
    ("match 4 (Kingambit)", 1980.0, ["Kingambit"]),
]


def _contains_species(roster, species_list):
    opp = [str(s).lower() for s in (roster.get("opponent_team") or [])]
    found = []
    for target in species_list:
        t = target.lower()
        if any(t in o or o in t for o in opp):
            found.append(target)
    return found


def _run_condition(client, hard_model, cheap_model, ffmpeg, start, workdir_base,
                    tag, rules, expected, repeats, use_crop):
    """Runs read_roster `repeats` times under one condition (crop on/off),
    each in its own workdir so ffmpeg's re-sampled frames don't collide.
    Returns per_species_hits (dict species -> count found across `repeats`
    runs) rather than one all-or-nothing tally - an earlier all-or-nothing
    version of this function reported "0/5" for a match where one of two
    expected species was found in EVERY single repeat, which buried a real,
    consistent, measurable win under a misleadingly bad-looking number."""
    real_crop = am.crop_opponent_icon_column
    if not use_crop:
        am.crop_opponent_icon_column = lambda frames, *a, **k: []
    per_species_hits = {sp: 0 for sp in expected}
    try:
        for r in range(repeats):
            workdir = os.path.join(workdir_base, f"{tag}_{r}")
            roster, _failed = am.read_roster(
                client, hard_model, cheap_model, ffmpeg, VIDEO, start, workdir, "", rules=rules)
            found = _contains_species(roster, expected)
            print(f"    [{tag} rep {r + 1}/{repeats}] opponent_team={roster.get('opponent_team')} "
                  f"-> found={found or 'NONE'}")
            for sp in found:
                per_species_hits[sp] += 1
    finally:
        am.crop_opponent_icon_column = real_crop
    return per_species_hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3,
                     help="how many times to call read_roster per condition (default 3)")
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY not set (check .env)")
    if not os.path.exists(VIDEO):
        sys.exit(f"Video not found: {VIDEO}")

    client = genai.Client(api_key=api_key)
    ffmpeg = am.find_ffmpeg()
    hard_model = "gemini-2.5-flash"
    cheap_model = "gemini-2.5-flash"
    rules = {"bring_count": 4, "team_size": 6}   # this job is doubles

    print(f"Running {args.repeats} repeat(s) per condition "
          f"({len(CASES) * 2 * args.repeats} real API calls total)...")

    for label, start, expected in CASES:
        print(f"\n=== {label} (start={start}s) ===")
        print(f"  expected opponent species: {expected}")
        workdir_base = os.path.join(WORKDIR_BASE, str(int(start)))

        old_per_species = _run_condition(
            client, hard_model, cheap_model, ffmpeg, start, workdir_base,
            "old", rules, expected, args.repeats, use_crop=False)
        new_per_species = _run_condition(
            client, hard_model, cheap_model, ffmpeg, start, workdir_base,
            "new", rules, expected, args.repeats, use_crop=True)

        print(f"  Per-species hit rate (out of {args.repeats}):")
        for sp in expected:
            old_n, new_n = old_per_species[sp], new_per_species[sp]
            verdict = ("IMPROVED" if new_n > old_n else
                       "REDUCED (investigate)" if new_n < old_n else
                       "no change")
            print(f"    {sp}: OLD {old_n}/{args.repeats}  ->  NEW {new_n}/{args.repeats}   [{verdict}]")


if __name__ == "__main__":
    main()
