"""
COMPARE CLASSIFIER MODELS - answers the real question before switching to a
cheaper model, instead of guessing: "does gemini-2.5-flash-lite actually
classify frames the same way gemini-2.5-flash does?" for structure_pass.py's
battle/team_preview/result/menu/other classification step.

Why this step specifically is a good candidate for a cheaper model: it's a
genuinely EASY question (a battle screen with HP bars looks nothing like a
menu or a webcam), and structure_pass.py's own docstring already calls it
"an easy question, so it's reliable." Gemini 2.5 Flash-Lite is dramatically
cheaper (2026 standard pricing: $0.10 / $0.40 per 1M input/output tokens, vs
$0.30 / $2.50 for standard 2.5 Flash - roughly 3-6x cheaper) - but "should be
fine for an easy task" is still a guess. This script gets you a real,
one-time, cheap comparison instead of switching blind and hoping, or never
switching because you're not sure.

Run it on a video you've ALREADY run structure_pass.py on (reuses the same
--frames-dir, so you don't pay to re-extract frames), or point it at a video
directly to sample fresh frames:

  py compare_classifier_models.py --video test.mp4 --frames-dir structure_frames
  py compare_classifier_models.py --video test.mp4 --limit 60   (cheap spot-check)

Cost note: this runs the SAME frames through TWO models, so it costs roughly
what one full structure_pass.py run on the candidate model alone would cost
(model A's pass is the "control" run you'd have paid for anyway if you were
going to run structure_pass.py at all). It's a small, ONE-TIME comparison
cost to make a permanent decision, not a new ongoing cost - once you've
decided, just pass --model gemini-2.5-flash-lite (or don't) to
structure_pass.py on every future run.
"""

import argparse
import os
import sys

import structure_pass as sp


def compare(frames, model_a, model_b, batch, concurrency):
    """Runs the exact same frame list through both models and returns
    (agreement_rate, disagreements). disagreements is a list of
    (timestamp, label_a, label_b) for every frame the two models disagreed
    on - small enough to review by hand even on a full video, since real
    disagreement should be rare for a task this easy."""
    labeled_a = sp.classify(frames, model_a, batch, concurrency)
    labeled_b = sp.classify(frames, model_b, batch, concurrency)

    disagreements = []
    agree = 0
    for (ts_a, lab_a), (ts_b, lab_b) in zip(labeled_a, labeled_b):
        if lab_a == lab_b:
            agree += 1
        else:
            disagreements.append((ts_a, lab_a, lab_b))
    rate = agree / len(labeled_a) if labeled_a else 0.0
    return rate, disagreements


def load_existing_frames(frames_dir, interval):
    """Reuses frames structure_pass.py already sampled (same s_%05d.jpg
    naming/ordering), so comparing models never costs a second frame
    extraction - only the two classification passes."""
    files = sorted(f for f in os.listdir(frames_dir) if f.startswith("s_") and f.endswith(".jpg"))
    return [(os.path.join(frames_dir, f), i * interval) for i, f in enumerate(files)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True)
    ap.add_argument("--interval", type=float, default=10.0, help="must match whatever --interval "
                    "structure_pass.py used, if reusing an existing --frames-dir")
    ap.add_argument("--model-a", default="gemini-2.5-flash", help="the current/control model")
    ap.add_argument("--model-b", default="gemini-2.5-flash-lite", help="the cheaper candidate model")
    ap.add_argument("--batch", type=int, default=20)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--frames-dir", default="structure_frames")
    ap.add_argument("--limit", type=int, default=0, help="only compare the first N sampled frames "
                    "(0 = all) - use this for a cheap spot-check instead of a full-video comparison")
    args = ap.parse_args()

    if not os.path.exists(args.video):
        sys.exit(f"Can't find: {args.video}")

    already_sampled = os.path.isdir(args.frames_dir) and os.listdir(args.frames_dir)
    if already_sampled:
        print(f"Reusing already-sampled frames in {args.frames_dir}/ (no re-extraction cost).")
        frames = load_existing_frames(args.frames_dir, args.interval)
    else:
        print(f"No existing {args.frames_dir}/ found - sampling fresh (free, local FFmpeg only).")
        ffmpeg = sp.find_ffmpeg()
        frames = sp.sample_frames(ffmpeg, args.video, args.frames_dir, args.interval)

    if not frames:
        sys.exit("No frames sampled.")
    if args.limit:
        frames = frames[:args.limit]
    print(f"Comparing {len(frames)} frames: {args.model_a}  vs  {args.model_b}\n")

    rate, disagreements = compare(frames, args.model_a, args.model_b, args.batch, args.concurrency)

    print("\n=============== MODEL COMPARISON ===============")
    print(f"{args.model_a}  vs  {args.model_b}")
    print(f"Agreement: {rate*100:.1f}% ({len(frames) - len(disagreements)}/{len(frames)} frames)")
    if disagreements:
        print(f"\n{len(disagreements)} disagreement(s) - check these specific timestamps by hand:")
        for ts, lab_a, lab_b in disagreements[:30]:
            print(f"  {ts:.0f}s: {args.model_a}={lab_a}  |  {args.model_b}={lab_b}")
        if len(disagreements) > 30:
            print(f"  ... and {len(disagreements) - 30} more")
        print(f"\nIf these are all in low-stakes labels (e.g. 'menu' vs 'other') and none "
              f"flip a real battle-vs-not-battle boundary, {args.model_b} is likely safe to "
              f"switch to for this step. If any disagreement changes a 'battle' call, don't "
              f"switch without looking at that exact frame first.")
    else:
        print(f"\nPerfect agreement on this sample - {args.model_b} looks safe to switch to.")
    print("==================================================")


if __name__ == "__main__":
    main()
