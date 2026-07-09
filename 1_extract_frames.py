"""
STEP 1 - Turn a raw recording into frames, automatically (FFmpeg).

The user never chops anything. They hand you a whole video; this step does
all the cutting for you. In your real product this exact logic runs on your
SERVER after upload -- here it runs on your machine so you can watch it work.

Two modes:

  uniform  - grab N frames per second across the whole video.
             Simple and predictable. Good for short clips.
               python 1_extract_frames.py --video myclip.mp4 --mode uniform --fps 1

  scene    - let FFmpeg find the moments where the screen actually changes
             and only keep frames from those. An 8-hour stream of mostly
             downtime becomes a few hundred frames instead of ~28,800.
             THIS is what makes long videos cheap and hands-off.
               python 1_extract_frames.py --video stream.mp4 --mode scene --threshold 0.4

Output:
  frames/ folder full of images, plus frames/manifest.csv that records the
  exact timestamp (in seconds) of every frame. Step 2 reads that manifest.

FFmpeg:
  You don't have to install FFmpeg by hand. `pip install imageio-ffmpeg`
  bundles a copy and this script will find it automatically. (If you already
  have real FFmpeg on your PATH, it'll use that instead.)
"""

import argparse
import concurrent.futures
import csv
import os
import re
import shutil
import subprocess
import sys


# ---- tunables ----------------------------------------------------------------
TOKENS_PER_FRAME = 258      # Gemini's approx token cost per image (default res)
GEMINI_INPUT_PRICE = 0.30   # USD per 1M input tokens (2.5 Flash, change if needed)
# -----------------------------------------------------------------------------


def find_ffmpeg():
    """Prefer the pip-bundled FFmpeg, fall back to one on the system PATH."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    sys.exit(
        "FFmpeg not found.\n"
        "Easiest fix:  pip install imageio-ffmpeg   (downloads a bundled copy)\n"
        "Or install FFmpeg yourself and add it to your PATH."
    )


def video_duration(ffmpeg, video):
    """Read the clip length (seconds) from FFmpeg's own output."""
    p = subprocess.run([ffmpeg, "-i", video], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", p.stderr)
    if m:
        h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        return h * 3600 + mn * 60 + s
    return None


def estimate(n_frames):
    tokens = n_frames * TOKENS_PER_FRAME
    cost = tokens / 1_000_000 * GEMINI_INPUT_PRICE
    return tokens, cost


def write_manifest(out_dir, rows):
    """rows = list of (filename, timestamp_seconds)."""
    with open(os.path.join(out_dir, "manifest.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["filename", "timestamp_seconds"])
        for name, ts in rows:
            w.writerow([name, round(ts, 2)])


def _seek_args(start, duration):
    """FFmpeg flags to analyze only part of a video (placed before -i for speed)."""
    a = []
    if start and start > 0:
        a += ["-ss", str(start)]
    if duration and duration > 0:
        a += ["-t", str(duration)]
    return a


def extract_uniform(ffmpeg, video, out_dir, fps, start=0.0, duration=0.0):
    os.makedirs(out_dir, exist_ok=True)
    out_pattern = os.path.join(out_dir, "frame_%05d.jpg")
    cmd = [ffmpeg, "-y", "-loglevel", "error"] + _seek_args(start, duration) + \
          ["-i", video, "-vf", f"fps={fps}", "-q:v", "3", out_pattern]
    subprocess.run(cmd, check=True)

    files = sorted(f for f in os.listdir(out_dir) if f.startswith("frame_") and f.endswith(".jpg"))
    # Timestamp = the slice start offset + position within the slice.
    rows = [(name, start + (i) / fps) for i, name in enumerate(files)]
    write_manifest(out_dir, rows)
    return rows


def extract_scene(ffmpeg, video, out_dir, threshold, start=0.0, duration=0.0):
    os.makedirs(out_dir, exist_ok=True)
    out_pattern = os.path.join(out_dir, "scene_%05d.jpg")
    # select='gt(scene,T)' keeps a frame whenever the scene-change score exceeds T.
    # showinfo prints each kept frame's pts_time (its timestamp) to stderr.
    cmd = [ffmpeg, "-y"] + _seek_args(start, duration) + \
          ["-i", video,
           "-vf", f"select='gt(scene,{threshold})',showinfo",
           "-vsync", "vfr", "-q:v", "3", out_pattern]
    p = subprocess.run(cmd, capture_output=True, text=True)

    times = [float(t) for t in re.findall(r"pts_time:([0-9.]+)", p.stderr)]
    files = sorted(f for f in os.listdir(out_dir) if f.startswith("scene_") and f.endswith(".jpg"))

    # pts_time restarts near 0 after a seek, so add the slice start offset.
    rows = []
    for i, name in enumerate(files):
        ts = (times[i] if i < len(times) else 0.0) + start
        rows.append((name, ts))
    write_manifest(out_dir, rows)
    return rows


def _extract_chunk(ffmpeg, video, out_dir, mode, fps, threshold, hwaccel, idx, start, dur):
    """One worker: extract its slice of the video. Files get a per-chunk prefix
    so parallel workers never collide. Returns (filename, absolute_timestamp) rows."""
    pre = [ffmpeg, "-y", "-loglevel", "error"]
    if hwaccel:
        pre += ["-hwaccel", hwaccel]
    if start and start > 0:
        pre += ["-ss", str(start)]
    if dur and dur > 0:
        pre += ["-t", str(dur)]
    prefix = f"seg{idx:03d}_"
    pattern = os.path.join(out_dir, prefix + "%05d.jpg")

    if mode == "uniform":
        subprocess.run(pre + ["-i", video, "-vf", f"fps={fps}", "-q:v", "3", pattern], check=True)
        files = sorted(f for f in os.listdir(out_dir) if f.startswith(prefix))
        return [(name, start + j / fps) for j, name in enumerate(files)]
    else:
        p = subprocess.run(pre + ["-i", video,
                                  "-vf", f"select='gt(scene,{threshold})',showinfo",
                                  "-vsync", "vfr", "-q:v", "3", pattern],
                           capture_output=True, text=True)
        times = [float(t) for t in re.findall(r"pts_time:([0-9.]+)", p.stderr)]
        files = sorted(f for f in os.listdir(out_dir) if f.startswith(prefix))
        return [(name, (times[j] if j < len(times) else 0.0) + start) for j, name in enumerate(files)]


def extract_parallel(ffmpeg, video, out_dir, mode, fps, threshold, jobs, hwaccel, base_start, span):
    """Split the video into time chunks and extract them all at once across CPU cores."""
    os.makedirs(out_dir, exist_ok=True)
    if not jobs or jobs <= 0:
        jobs = min(os.cpu_count() or 4, 12)   # auto: use all cores (capped)

    if not span or span <= 0:
        jobs = 1
        chunks = [(0, base_start, 0.0)]        # unknown length: one worker, whole video
    else:
        size = span / jobs
        chunks = [(i, base_start + i * size, size) for i in range(jobs)]

    print(f"Parallel extraction: {jobs} worker(s)" + (f", hwaccel={hwaccel}" if hwaccel else ""))
    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
        futures = [ex.submit(_extract_chunk, ffmpeg, video, out_dir, mode, fps,
                             threshold, hwaccel, i, s, d) for (i, s, d) in chunks]
        for fut in concurrent.futures.as_completed(futures):
            rows.extend(fut.result())

    rows.sort(key=lambda r: r[1])              # global time order
    write_manifest(out_dir, rows)
    return rows


def main():
    parser = argparse.ArgumentParser(description="Extract frames from a recording with FFmpeg.")
    parser.add_argument("--video", required=True, help="Path to the video (any length)")
    parser.add_argument("--out", default="frames", help="Output folder (default: frames)")
    parser.add_argument("--mode", choices=["uniform", "scene"], default="uniform",
                        help="uniform = N frames/sec; scene = only on screen changes")
    parser.add_argument("--fps", type=float, default=1.0, help="[uniform] frames per second")
    parser.add_argument("--threshold", type=float, default=0.4,
                        help="[scene] 0.1=very sensitive, 0.6=only big changes (default 0.4)")
    parser.add_argument("--start", type=float, default=0.0,
                        help="Start this many seconds into the video (default 0)")
    parser.add_argument("--duration", type=float, default=0.0,
                        help="Only analyze this many seconds from --start (0 = whole video)")
    parser.add_argument("--jobs", type=int, default=1,
                        help="Parallel workers. 1=sequential (default), 0=auto (all CPU cores). Big speedup on long videos.")
    parser.add_argument("--hwaccel", default="",
                        help="Hardware decode, e.g. 'd3d11va' for AMD/Windows. Speeds decoding; drop it if it errors.")
    args = parser.parse_args()

    if not os.path.exists(args.video):
        sys.exit(f"Can't find the video: {args.video}")

    ffmpeg = find_ffmpeg()
    dur = video_duration(ffmpeg, args.video)
    if dur:
        print(f"Video length: {dur/60:.1f} min ({dur:.0f}s)")

    if args.duration:
        print(f"Slice: {args.duration:.0f}s starting at {args.start:.0f}s")

    mode_desc = f"{args.fps} fps" if args.mode == "uniform" else f"scene threshold {args.threshold}"
    print(f"Mode: {args.mode} ({mode_desc})")

    if args.jobs != 1:
        span = args.duration if args.duration > 0 else (dur or 0)
        rows = extract_parallel(ffmpeg, args.video, args.out, args.mode, args.fps,
                                args.threshold, args.jobs, args.hwaccel or "", args.start, span)
    elif args.mode == "uniform":
        rows = extract_uniform(ffmpeg, args.video, args.out, args.fps, args.start, args.duration)
    else:
        rows = extract_scene(ffmpeg, args.video, args.out, args.threshold, args.start, args.duration)

    n = len(rows)
    tokens, cost = estimate(n)
    print(f"\nKept {n} frames -> '{args.out}' folder (+ manifest.csv with timestamps)")
    print(f"Rough Gemini cost to analyze these: ~{tokens:,} input tokens ≈ ${cost:.3f}")
    if args.mode == "uniform" and dur and dur > 600:
        full = int(dur * args.fps)
        print(f"(Tip: this is a long video. Try --mode scene to keep far fewer than {full:,} frames.)")
    if n == 0:
        print("No frames kept. For scene mode, try a lower --threshold (e.g. 0.2).")


if __name__ == "__main__":
    main()
