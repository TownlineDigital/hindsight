"""
TRANSCRIPT - rip the streamer's commentary into a timestamped transcript.

Why: the commentary is a second signal that often states Pokemon names, calls match
boundaries ("next game", "GG"), explains outcomes, and captures the player's REASONING
(gold for coaching + the AI chat). Fuses with the visual events by timestamp.

Uses faster-whisper (CPU-friendly). Install once:
    pip install faster-whisper

Run:
    py transcribe.py --video test.mp4
    py transcribe.py --video test.mp4 --matches matches.csv   (only transcribe match windows - faster)
    py transcribe.py --video test.mp4 --model base            (smaller/faster, less accurate)

Output: transcript.json  ->  [{start, end, text, match}]
"""

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys


def find_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    sys.exit("FFmpeg not found. Run: pip install imageio-ffmpeg")


def extract_audio(ffmpeg, video, out_wav, start=None, duration=None):
    cmd = [ffmpeg, "-y", "-loglevel", "error"]
    if start is not None:
        cmd += ["-ss", str(start)]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += ["-i", video, "-ac", "1", "-ar", "16000", "-vn", out_wav]
    subprocess.run(cmd, check=True)


def load_model(size):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper not installed. Run:  pip install faster-whisper")
    # int8 keeps it fast on CPU; swap device='cuda' if you set up a GPU build
    return WhisperModel(size, device="cpu", compute_type="int8")


def transcribe_file(model, wav, time_offset=0.0):
    segments, _ = model.transcribe(wav, vad_filter=True)
    out = []
    for s in segments:
        txt = (s.text or "").strip()
        if txt:
            out.append({"start": round(s.start + time_offset, 1),
                        "end": round(s.end + time_offset, 1), "text": txt})
    return out


def load_matches(path):
    with open(path, newline="", encoding="utf-8") as f:
        return [(int(r["match"]), float(r["start_seconds"]), float(r["end_seconds"]))
                for r in csv.DictReader(f)]


def main():
    ap = argparse.ArgumentParser(description="Transcribe stream commentary to transcript.json")
    ap.add_argument("--video", required=True)
    ap.add_argument("--model", default="small", help="faster-whisper size: tiny/base/small/medium")
    ap.add_argument("--matches", default="", help="matches.csv - transcribe only those windows (faster)")
    ap.add_argument("--out", default="transcript.json")
    ap.add_argument("--workdir", default="audio_tmp")
    args = ap.parse_args()

    if not os.path.exists(args.video):
        sys.exit(f"Can't find: {args.video}")

    ffmpeg = find_ffmpeg()
    os.makedirs(args.workdir, exist_ok=True)
    print(f"Loading faster-whisper '{args.model}' (first run downloads the model)...")
    model = load_model(args.model)

    transcript = []
    if args.matches and os.path.exists(args.matches):
        matches = load_matches(args.matches)
        print(f"Transcribing {len(matches)} match windows...")
        for mi, start, end in matches:
            wav = os.path.join(args.workdir, f"m{mi:03d}.wav")
            extract_audio(ffmpeg, args.video, wav, start=start, duration=max(1.0, end - start))
            segs = transcribe_file(model, wav, time_offset=start)
            for s in segs:
                s["match"] = mi
            transcript.extend(segs)
            os.remove(wav)
            print(f"  match {mi}: {len(segs)} segments", end="\r")
        print()
    else:
        print("Transcribing the whole video (this can take a while on CPU)...")
        wav = os.path.join(args.workdir, "full.wav")
        extract_audio(ffmpeg, args.video, wav)
        transcript = transcribe_file(model, wav)
        os.remove(wav)

    transcript.sort(key=lambda s: s["start"])
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)
    shutil.rmtree(args.workdir, ignore_errors=True)

    words = sum(len(s["text"].split()) for s in transcript)
    print(f"\nDone. {len(transcript)} segments, ~{words} words -> {args.out}")


if __name__ == "__main__":
    main()
