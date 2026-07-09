"""
Run the FULL match-aware pipeline end-to-end, unattended.

  py run_full.py                         (uses test2.mp4, gemini-3.5-flash, max accuracy)
  py run_full.py --video myvod.mp4
  py run_full.py --model gemini-2.5-flash   (cheaper)

Order:
  1. compose schema (per-turn state)
  2. structure_pass    -> matches.csv          (find every match)
  3. analyze_matches   -> events.json          (roster-locked events + winners)
  4. battle record     -> battle_record.csv
  5. player report     -> player_report.md
  6. coach report      -> coach_report.md
  7. transcript        -> transcript.json      (OPTIONAL - needs faster-whisper; won't block the rest)

Critical steps stop the run (and tell you which failed). The transcript is optional, so a
missing Whisper install can't cost you the reports. Everything saves as it goes.

Needs GEMINI_API_KEY set and billing on.
"""

import argparse
import os
import shutil
import subprocess
import sys


def main():
    ap = argparse.ArgumentParser(description="Run the full footage-to-coaching pipeline.")
    ap.add_argument("--url", default="", help="Twitch/YouTube VOD URL to download first (needs yt-dlp)")
    ap.add_argument("--video", default="test2.mp4")
    ap.add_argument("--model", default="gemini-2.5-flash", help="cheap model for the bulk (default 2.5 Flash)")
    ap.add_argument("--hard-model", default="gemini-3.5-flash", help="stronger model for the few hard reads (roster+winner)")
    ap.add_argument("--interval", default="10", help="structure-pass sample interval seconds")
    ap.add_argument("--battle-fps", default="0.33", help="battle sampling fps (0.33 = every 3s)")
    ap.add_argument("--frame-width", default="640", help="battle frame width px (lower = cheaper)")
    ap.add_argument("--batch", default="10")
    ap.add_argument("--concurrency", default="8")
    ap.add_argument("--hwaccel", default="", help="GPU decode (e.g. d3d11va). Off by default for unattended reliability.")
    ap.add_argument("--whisper", default="small", help="faster-whisper size: base/small/medium")
    ap.add_argument("--limit", default="0", help="analyze only first N matches (0 = all)")
    args = ap.parse_args()

    py = sys.executable
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY is not set in this terminal. Set it, then re-run.")

    # step 0: download the VOD if a URL was given
    if args.url:
        print(f"\n========== STEP 0: Download VOD ==========\n{args.url}", flush=True)
        try:
            from fetch_vod import download
        except ImportError:
            sys.exit("fetch_vod.py not found next to run_full.py.")
        args.video = download(args.url, "vod")
        print(f"  OK  downloaded -> {args.video}")

    if not os.path.exists(args.video):
        sys.exit(f"Can't find '{args.video}'. Put your video in this folder named '{args.video}', "
                 "pass --video, or pass --url to download one.")

    # clear stale outputs from any previous run
    for f in ["matches.csv", "events.json", "events.csv", "transcript.json",
              "battle_record.csv", "player_report.md", "coach_report.md"]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                sys.exit(f"Can't delete old '{f}' — it's open in another program (e.g. Excel). "
                         "Close it and re-run.")
    for d in ["structure_frames", "match_frames", "frames", "audio_tmp"]:
        shutil.rmtree(d, ignore_errors=True)

    analyze = ["analyze_matches.py", "--video", args.video, "--model", args.model,
               "--hard-model", args.hard_model, "--battle-fps", args.battle_fps,
               "--frame-width", args.frame_width, "--batch", args.batch, "--concurrency", args.concurrency]
    if args.hwaccel:
        analyze += ["--hwaccel", args.hwaccel]
    if args.limit and args.limit != "0":
        analyze += ["--limit", args.limit]

    steps = [
        ("Compose schema", ["compose_schema.py", "--game", "pokemon", "--mode", "doubles"], False),
        ("Find matches (structure pass)",
         ["structure_pass.py", "--video", args.video, "--interval", args.interval,
          "--model", args.model, "--concurrency", args.concurrency], False),
        ("Per-match analysis", analyze, False),
        ("Battle record", ["battle_record.py"], False),
        ("Player report", ["player_report.py"], False),
        ("Coach report", ["coach_report.py"], False),
        ("Transcript (optional)",
         ["transcribe.py", "--video", args.video, "--matches", "matches.csv", "--model", args.whisper], True),
    ]

    try:
        for i, (name, cmd, optional) in enumerate(steps, 1):
            print(f"\n========== STEP {i}/{len(steps)}: {name} ==========", flush=True)
            rc = subprocess.run([py] + cmd).returncode
            if rc != 0:
                if optional:
                    print(f"  (optional step '{name}' failed, exit {rc} — continuing; your reports are already done.)")
                    continue
                print(f"\n  X  STOPPED — step {i} ({name}) FAILED with exit {rc}. Steps after it did not run.")
                sys.exit(rc)
            print(f"  OK  {name}")
    except KeyboardInterrupt:
        print("\nInterrupted by you. Whatever finished is saved to disk.")
        sys.exit(130)

    print("\n==================================================")
    print("  ALL DONE.")
    print("  Outputs: events.json/csv, battle_record.csv, player_report.md, coach_report.md")
    print("           transcript.json (if Whisper ran)")
    print("  Then ask the coach:  py coach_chat.py")
    print("==================================================")


if __name__ == "__main__":
    main()
