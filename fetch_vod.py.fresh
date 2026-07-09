"""
Download a Twitch (or YouTube) VOD into this folder with a safe, fixed filename.

Saves to vod.<ext> (no title-with-spaces problems), and prints the path. Used by
run_full.py via --url, or standalone:

  py fetch_vod.py --url https://www.twitch.tv/videos/2808818431

Install once:  py -m pip install -U yt-dlp
"""

import argparse
import glob
import os
import shutil
import sys


def download(url, out_basename="vod"):
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        sys.exit("yt-dlp not installed. Run:  py -m pip install -U yt-dlp")

    # clear any previous download so re-runs don't pile up / collide
    for f in glob.glob(out_basename + ".*"):
        try:
            os.remove(f)
        except OSError:
            pass

    opts = {
        "outtmpl": out_basename + ".%(ext)s",
        "noplaylist": True,
        # prefer a single mp4 when available; fall back to best
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
    }
    # Prefer a REAL system ffmpeg (the Dockerfile apt-installs one on PATH for
    # the deployed server) over the pip-bundled imageio_ffmpeg fallback below.
    # This check has to come FIRST and be decisive: yt-dlp prioritizes an
    # explicit `ffmpeg_location` over its own PATH auto-detection, so if the
    # imageio_ffmpeg block unconditionally set ffmpeg_location whenever
    # get_ffmpeg_exe() didn't raise - the original bug here - it would
    # SILENTLY OVERRIDE a perfectly good system ffmpeg with a broken
    # pip-bundled one, even after the system ffmpeg was installed and
    # confirmed working. That's exactly what happened 2026-07-09: apt-
    # installing ffmpeg in the Dockerfile alone did NOT fix a live "ffmpeg
    # could not be found" failure, because get_ffmpeg_exe() returning A path
    # doesn't mean that path's binary is actually executable - it can return
    # successfully while pointing at a binary that fails the moment yt-dlp
    # tries to run it, and by then ffmpeg_location has already been pinned to
    # the bad path instead of ever letting yt-dlp look at PATH itself.
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        print(f"Using system ffmpeg: {system_ffmpeg}", file=sys.stderr)
    else:
        # No system ffmpeg found (e.g. a local dev machine that hasn't
        # installed it) - fall back to the pip-bundled binary. Deliberately
        # prints (not silently swallows) any failure here: a bare
        # `except: pass` on this exact line is what turned a real
        # "ffmpeg isn't working" problem into a confusing unrelated-looking
        # "m3u8 download detected but ffmpeg could not be found" error out of
        # yt-dlp instead of a clear diagnostic.
        try:
            import imageio_ffmpeg
            opts["ffmpeg_location"] = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
            print(f"No system ffmpeg found - using pip-bundled fallback at "
                  f"{opts['ffmpeg_location']}", file=sys.stderr)
        except Exception as e:
            print(f"Note: no system ffmpeg found, and the pip-bundled ffmpeg fallback "
                  f"also failed ({e}). Video download will likely fail if this format "
                  f"needs ffmpeg (e.g. an HLS/m3u8 stream, which is how Twitch serves VODs).",
                  file=sys.stderr)

    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)

    if not os.path.exists(path):
        # merge/remux may change the extension; find the finished file
        cands = [f for f in glob.glob(out_basename + ".*") if not f.endswith((".part", ".ytdl"))]
        if cands:
            path = max(cands, key=os.path.getsize)
    if not os.path.exists(path):
        sys.exit("Download reported success but the output file wasn't found.")
    return path


def main():
    ap = argparse.ArgumentParser(description="Download a Twitch/YouTube VOD to vod.<ext>")
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", default="vod", help="output basename (default: vod)")
    args = ap.parse_args()
    path = download(args.url, args.out)
    print(f"\nDownloaded -> {path}")


if __name__ == "__main__":
    main()
