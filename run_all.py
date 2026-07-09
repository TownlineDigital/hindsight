"""
Run the whole pipeline end-to-end, stopping (and telling you what failed) if any
step errors out.

  py run_all.py
  py run_all.py --threshold 0.4
  py run_all.py --video test.mp4 --model gemini-2.5-flash --threshold 0.3

Steps, in order:
  1. clear old frames
  2. extract frames (scene detection, all CPU cores + AMD GPU decode)
  3. analyze with Gemini  -> events.json / events.csv
  4. battle record        -> battle_record.csv
  5. player report        -> player_report.md

Requires: GEMINI_API_KEY set in this terminal, and billing enabled (the analyze
step makes many requests). Each step saves its own output, so a failure later on
doesn't lose earlier results.
"""

import argparse
import os
import shutil
import subprocess
import sys


def main():
    ap = argparse.ArgumentParser(description="Run the full footage-to-player-report pipeline.")
    ap.add_argument("--video", default="test.mp4")
    ap.add_argument("--threshold", default="0.3", help="scene-detection threshold (default 0.3)")
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--hwaccel", default="d3d11va", help="GPU decode; pass '' to disable")
    ap.add_argument("--jobs", default="0", help="extraction workers (0 = all cores)")
    args = ap.parse_args()

    py = sys.executable  # the exact Python running this script (has your packages)

    extract = ["1_extract_frames.py", "--video", args.video, "--mode", "scene",
               "--threshold", str(args.threshold), "--jobs", str(args.jobs)]
    if args.hwaccel:
        extract += ["--hwaccel", args.hwaccel]

    steps = [
        ("Extract frames", extract),
        ("Analyze with Gemini", ["2_analyze_gemini.py", "--model", args.model]),
        ("Battle record", ["4_battle_record.py"]),
        ("Player report", ["5_player_report.py"]),
    ]

    # step 0: clear old frames
    if os.path.isdir("frames"):
        shutil.rmtree("frames", ignore_errors=True)
        print("Cleared old frames/\n")

    try:
        for i, (name, cmd) in enumerate(steps, 1):
            print(f"\n========== STEP {i}/{len(steps)}: {name} ==========", flush=True)
            rc = subprocess.run([py] + cmd).returncode
            if rc != 0:
                print(f"\n  X  STOPPED — step {i} ({name}) FAILED with exit code {rc}.")
                print("     Steps after it did not run. Fix the issue above and re-run.")
                sys.exit(rc)
            print(f"  OK  step {i} ({name}) done.")
    except KeyboardInterrupt:
        print("\nInterrupted by you. Whatever finished has been saved to disk.")
        sys.exit(130)

    print("\n==================================================")
    print("  ALL STEPS FINISHED.")
    print("  Outputs: events.json, events.csv, battle_record.csv, player_report.md")
    print("==================================================")


if __name__ == "__main__":
    main()
