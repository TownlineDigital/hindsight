"""
STRUCTURE PASS - reliably find every match in a long video.

The problem: catching one transient screen (team preview / result) by luck is
unreliable, and overlay signals (a W/L counter) aren't on every stream. The fix:
classify the game's OWN state - is each moment an active battle or not - then each
contiguous run of 'battle' = one match. A battle lasts minutes, so you can't miss
it, and it needs nothing streamer-specific.

What it does:
  1. Samples the whole video at a regular interval (default every 10s).
  2. Cheaply classifies each frame: battle / team_preview / result / menu / other.
  3. Groups contiguous battle stretches into matches (merging brief gaps).
  4. Writes matches.csv (one row per match: index, start, end) - the foundation
     the per-match analysis then runs inside.

Run it:
  py structure_pass.py --video test.mp4
  py structure_pass.py --video test.mp4 --interval 8 --model gemini-2.5-flash
"""

import argparse
import concurrent.futures
import csv
import json
import os
import re
import shutil
import subprocess
import sys

try:
    from google import genai
    from google.genai import types
except ImportError:
    # Same reasoning as analyze_matches.py: don't kill the whole module on
    # import just because google-genai isn't installed - segment_matches()
    # and other pure logic (and anything importing this module, e.g.
    # compare_classifier_models.py) needs no API client at all. The actual
    # dependency is only required once classify_batch()/classify() run.
    genai = None
    types = None
    _GENAI_IMPORT_ERROR = "Run:  pip install google-genai"
else:
    _GENAI_IMPORT_ERROR = None

CONTEXT = ("frames from a Pokemon Champions DOUBLES stream. A 'battle' shows an active "
           "Pokemon battle (Pokemon on the field with HP bars / battle UI). 'team_preview' is "
           "the pre-battle screen showing both players' 6 Pokemon to pick from. 'result' is the "
           "end-of-match win/loss / results / rating screen. 'menu' is menus, matchmaking, or "
           "loading. 'other' is anything else (just a webcam, intermission, desktop).")
LABELS = ["battle", "team_preview", "result", "menu", "other"]


def find_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    sys.exit("FFmpeg not found. Run:  pip install imageio-ffmpeg")


def sample_frames(ffmpeg, video, out_dir, interval, scale_w=512):
    os.makedirs(out_dir, exist_ok=True)
    fps = 1.0 / interval
    pattern = os.path.join(out_dir, "s_%05d.jpg")
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", video,
                    "-vf", f"fps={fps},scale={scale_w}:-1", "-q:v", "5", pattern], check=True)
    files = sorted(f for f in os.listdir(out_dir) if f.startswith("s_") and f.endswith(".jpg"))
    # frame k (1-based) sits at (k-1)*interval seconds
    return [(os.path.join(out_dir, f), (i) * interval) for i, f in enumerate(files)]


def classify_batch(client, model, paths):
    if _GENAI_IMPORT_ERROR:
        sys.exit(_GENAI_IMPORT_ERROR)
    prompt = (f"You are classifying {CONTEXT}\n\n"
              f"For EACH of the {len(paths)} images, output exactly one label from "
              f"{LABELS}. Return ONLY a JSON array of {len(paths)} label strings, in the same "
              "order as the images. No other text.")
    parts = [prompt]
    for p in paths:
        with open(p, "rb") as img:
            parts.append(types.Part.from_bytes(data=img.read(), mime_type="image/jpeg"))
    resp = client.models.generate_content(
        model=model, contents=parts,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0))
    text = (resp.text or "").strip()
    try:
        labels = json.loads(text)
    except Exception:
        m = re.search(r"\[.*\]", text, re.DOTALL)
        labels = json.loads(m.group(0)) if m else []
    out = []
    for i in range(len(paths)):
        lab = str(labels[i]).lower().strip() if i < len(labels) else "other"
        out.append(lab if lab in LABELS else "other")
    return out


def classify(frames, model, batch, concurrency):
    if _GENAI_IMPORT_ERROR:
        sys.exit(_GENAI_IMPORT_ERROR)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("No API key. Set GEMINI_API_KEY first.")
    client = genai.Client(api_key=api_key)
    jobs = [frames[i:i + batch] for i in range(0, len(frames), batch)]
    results = {}

    def work(idx, chunk):
        paths = [p for p, _ in chunk]
        return idx, classify_batch(client, model, paths)

    print(f"Classifying {len(frames)} frames in {len(jobs)} batches ({concurrency} parallel)...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = {ex.submit(work, i, c): i for i, c in enumerate(jobs)}
        done = 0
        for fut in concurrent.futures.as_completed(futs):
            try:
                idx, labels = fut.result()
                results[idx] = labels
            except Exception as e:
                results[futs[fut]] = None
                print(f"  batch error -> {str(e)[:100]}")
            done += 1
            print(f"  {done}/{len(jobs)} batches done", end="\r")
    print()

    labeled = []
    for i, chunk in enumerate(jobs):
        labels = results.get(i) or ["other"] * len(chunk)
        for (path, ts), lab in zip(chunk, labels):
            labeled.append((ts, lab))
    labeled.sort(key=lambda x: x[0])
    return labeled


def segment_matches(labeled, interval, merge_gap, min_duration):
    runs = []
    cur = None
    for ts, lab in labeled:
        if lab == "battle":
            if cur is None:
                cur = [ts, ts]
            else:
                cur[1] = ts
        else:
            if cur is not None:
                runs.append(cur)
                cur = None
    if cur is not None:
        runs.append(cur)

    # merge battle runs separated by a short non-battle gap (mid-battle misclassification)
    merged = []
    for r in runs:
        if merged and (r[0] - merged[-1][1]) <= merge_gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)

    # a real match spans at least min_duration; drop blips
    matches = [(s, e + interval) for s, e in merged if (e - s) >= min_duration]
    return matches, runs


def main():
    ap = argparse.ArgumentParser(description="Find every match in a video by the battle/not-battle cycle.")
    ap.add_argument("--video", required=True)
    ap.add_argument("--interval", type=float, default=10.0, help="seconds between sampled frames (default 10)")
    ap.add_argument("--model", default="gemini-2.5-flash", help="cheap classifier model")
    ap.add_argument("--batch", type=int, default=20, help="frames per request")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--merge-gap", type=float, default=40.0, help="bridge battle runs separated by <= this many seconds")
    ap.add_argument("--min-duration", type=float, default=60.0, help="ignore battle runs shorter than this")
    ap.add_argument("--out", default="matches.csv")
    ap.add_argument("--frames-dir", default="structure_frames")
    args = ap.parse_args()

    if not os.path.exists(args.video):
        sys.exit(f"Can't find: {args.video}")

    ffmpeg = find_ffmpeg()
    print(f"Sampling 1 frame / {args.interval:.0f}s ...")
    frames = sample_frames(ffmpeg, args.video, args.frames_dir, args.interval)
    if not frames:
        sys.exit("No frames sampled.")
    print(f"  {len(frames)} frames sampled.")

    labeled = classify(frames, args.model, args.batch, args.concurrency)
    matches, _ = segment_matches(labeled, args.interval, args.merge_gap, args.min_duration)

    from collections import Counter
    counts = Counter(lab for _, lab in labeled)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["match", "start_seconds", "end_seconds", "duration_seconds"])
        for i, (s, e) in enumerate(matches, 1):
            w.writerow([i, round(s, 1), round(e, 1), round(e - s, 1)])

    print("\n=============== STRUCTURE PASS ===============")
    print(f"Frame states: " + ", ".join(f"{k}={counts.get(k,0)}" for k in LABELS))
    print(f"MATCHES FOUND: {len(matches)}")
    if matches:
        total = sum(e - s for s, e in matches)
        print(f"Avg match length: {total/len(matches)/60:.1f} min")
    print(f"Wrote {args.out}")
    print("==============================================")
    print("\nNext: run per-match analysis inside each window (roster + events).")


if __name__ == "__main__":
    main()
