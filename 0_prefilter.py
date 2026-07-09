"""
STEP 0 (for LONG videos) - Decide what's even worth analyzing, cheaply.

The idea (a "model cascade"): before paying the expensive AI, run a fast,
free pass that throws away the boring parts - menus, loading screens, idle
downtime - and keeps only the active gameplay. On a long upload this can drop
80-90% of the footage before Gemini ever sees it.

This version uses zero machine learning. Just two cheap signals per moment:
  * motion    - how much the picture changed since the last sample (action)
  * brightness- near-black / very dark frames (loading, transitions)
A moment is "active" if there's enough motion and it isn't basically black.
Adjacent active moments get merged into segments (with a little padding).

It does NOT modify your video. It writes:
  * keep_segments.csv   - the start/end seconds worth analyzing
  * a printed report     - how much it dropped and the estimated Gemini saving

Where YOLO plugs in later:
  See classify_window_with_yolo() near the bottom. Once you've trained a
  small YOLO model on your game, you can replace/augment the motion test with
  "does this window actually contain gameplay?" for much sharper filtering.

Run it:
  python 0_prefilter.py --video longstream.mp4
  python 0_prefilter.py --video longstream.mp4 --motion 6 --window 4
"""

import argparse
import csv
import sys

try:
    import cv2
except ImportError:
    sys.exit("OpenCV isn't installed. Run:  pip install opencv-python")


# ---- cost assumptions (match step 1) ----------------------------------------
TOKENS_PER_FRAME = 258
GEMINI_INPUT_PRICE = 0.30   # USD per 1M input tokens (2.5 Flash)
# -----------------------------------------------------------------------------


def sample_signals(video, sample_fps):
    """Walk the video at sample_fps and return [(t_seconds, motion, brightness)]."""
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        sys.exit(f"OpenCV couldn't open the video: {video}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = total / fps if fps else 0
    step = max(1, int(round(fps / sample_fps)))

    signals = []
    prev = None
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % step == 0:
            small = cv2.resize(frame, (160, 90))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            brightness = float(gray.mean())
            if prev is None:
                motion = 0.0
            else:
                motion = float(cv2.absdiff(gray, prev).mean())
            prev = gray
            signals.append((idx / fps, motion, brightness))
        idx += 1

    cap.release()
    return signals, duration


def windows_from_signals(signals, window, motion_thresh, dark_thresh):
    """Group samples into fixed time windows; mark each active or idle."""
    if not signals:
        return []
    out = []
    bucket = []
    start = signals[0][0]
    for t, motion, bright in signals:
        if t - start >= window and bucket:
            out.append(_summarize(start, t, bucket, motion_thresh, dark_thresh))
            bucket = []
            start = t
        bucket.append((motion, bright))
    if bucket:
        end = signals[-1][0] + (signals[1][0] - signals[0][0] if len(signals) > 1 else 1)
        out.append(_summarize(start, end, bucket, motion_thresh, dark_thresh))
    return out


def _summarize(start, end, bucket, motion_thresh, dark_thresh):
    avg_motion = sum(m for m, _ in bucket) / len(bucket)
    avg_bright = sum(b for _, b in bucket) / len(bucket)
    active = (avg_motion >= motion_thresh) and (avg_bright >= dark_thresh)
    return {"start": start, "end": end, "motion": avg_motion,
            "brightness": avg_bright, "active": active}


def merge_active(windows, pad):
    """Turn active windows into merged, padded keep-segments."""
    segments = []
    cur = None
    for w in windows:
        if w["active"]:
            s, e = max(0, w["start"] - pad), w["end"] + pad
            if cur and s <= cur[1]:
                cur[1] = max(cur[1], e)
            else:
                if cur:
                    segments.append(cur)
                cur = [s, e]
        # idle windows just break the current run on the next active one
    if cur:
        segments.append(cur)
    return segments


def estimate_cost(seconds, target_fps):
    frames = seconds * target_fps
    tokens = frames * TOKENS_PER_FRAME
    return frames, tokens, tokens / 1_000_000 * GEMINI_INPUT_PRICE


def main():
    p = argparse.ArgumentParser(description="Cheaply pre-filter a long video before Gemini.")
    p.add_argument("--video", required=True, help="Path to the (possibly very long) video")
    p.add_argument("--sample-fps", type=float, default=1.0, help="How often to sample for analysis (default 1/sec)")
    p.add_argument("--window", type=float, default=4.0, help="Seconds per decision window (default 4)")
    p.add_argument("--motion", type=float, default=6.0, help="Motion threshold; lower keeps more (default 6)")
    p.add_argument("--dark", type=float, default=20.0, help="Below this avg brightness = treated as idle/black (default 20)")
    p.add_argument("--pad", type=float, default=2.0, help="Seconds of padding around kept segments (default 2)")
    p.add_argument("--target-fps", type=float, default=1.0, help="Frames/sec you'll send to Gemini, for the estimate (default 1)")
    p.add_argument("--out", default="keep_segments.csv", help="Where to write the keep-segments")
    args = p.parse_args()

    print("Scanning (this is the cheap pass, no AI)...")
    signals, duration = sample_signals(args.video, args.sample_fps)
    windows = windows_from_signals(signals, args.window, args.motion, args.dark)
    segments = merge_active(windows, args.pad)

    kept = sum(e - s for s, e in segments)
    kept = min(kept, duration) if duration else kept
    dropped = max(0.0, duration - kept) if duration else 0.0
    pct_drop = (dropped / duration * 100) if duration else 0.0

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["start_seconds", "end_seconds", "duration_seconds"])
        for s, e in segments:
            w.writerow([round(s, 2), round(e, 2), round(e - s, 2)])

    # Report
    print("\n================ PRE-FILTER REPORT ================")
    if duration:
        print(f"Total video:     {duration/60:6.1f} min ({duration:.0f}s)")
    print(f"Kept (active):   {kept/60:6.1f} min  in {len(segments)} segment(s)")
    print(f"Dropped (idle):  {dropped/60:6.1f} min   -> {pct_drop:.0f}% of the video")

    f_full, _, c_full = estimate_cost(duration, args.target_fps) if duration else (0, 0, 0)
    f_keep, _, c_keep = estimate_cost(kept, args.target_fps)
    print("\nEstimated Gemini cost (at {:.1f} fps):".format(args.target_fps))
    print(f"  analyze everything: {f_full:>8,.0f} frames  ~${c_full:.3f}")
    print(f"  analyze kept only:  {f_keep:>8,.0f} frames  ~${c_keep:.3f}")
    if c_full > 0:
        print(f"  estimated saving:   ${c_full - c_keep:.3f}  ({(1-c_keep/c_full)*100:.0f}% cheaper)")
    print("===================================================")
    print(f"\nWrote {args.out}. Next: extract frames only from these segments, then run Gemini.")
    if pct_drop < 5 and duration:
        print("Tip: very little was dropped. Lower --motion or raise --dark to filter more aggressively.")


# --------------------------------------------------------------------------
# YOLO HOOK (for later — not used yet)
# --------------------------------------------------------------------------
def classify_window_with_yolo(frames):
    """
    PLACEHOLDER for when you train a small YOLO model on your game.

    Today this file decides 'active' from motion + brightness alone. Once you
    have a trained model (e.g. yolo11n) you can make the decision much sharper:
    detect whether a window actually contains gameplay UI (HUD, health bars,
    characters) rather than a menu or spectator screen.

    Sketch:
        from ultralytics import YOLO
        model = YOLO("your_game_yolo11n.pt")     # your trained weights
        results = model(frames)                   # run on a few frames
        # return True if it sees gameplay classes, else False
        return any(len(r.boxes) > 0 for r in results)

    Then in windows_from_signals(), combine this with the motion test, e.g.
    active = motion_ok AND classify_window_with_yolo(window_frames).
    """
    raise NotImplementedError("Train a YOLO model first, then wire this in.")


if __name__ == "__main__":
    main()
