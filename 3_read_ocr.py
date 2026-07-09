"""
STEP 3 (OPTIONAL) — Read exact on-screen text with PaddleOCR.

Why this is separate and optional:
  Gemini is great at understanding *what is happening*, but it can be
  sloppy with exact numbers (HP 247 vs 241). PaddleOCR reads text
  deterministically, so it's the reliable way to capture precise numbers
  like HP, damage, timers, gold, ammo.

  Do step 2 (Gemini) FIRST. Only add this once you've confirmed the basic
  idea works and you need number-precision. PaddleOCR is a heavier install,
  so if it fights you during setup, skip it for now -- you're not blocked.

What it does:
  Runs OCR over every image in frames/ and writes ocr_text.csv:
    frame, text, confidence

Run it:
  python 3_read_ocr.py
"""

import argparse
import csv
import os
import sys

try:
    from paddleocr import PaddleOCR
except ImportError:
    sys.exit("PaddleOCR isn't installed. Run:  pip install paddlepaddle paddleocr")


def run_ocr(frames_dir="frames", out_csv="ocr_text.csv"):
    if not os.path.isdir(frames_dir):
        sys.exit(f"No '{frames_dir}' folder. Run step 1 first.")

    files = sorted(
        f for f in os.listdir(frames_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    )
    if not files:
        sys.exit(f"No images in '{frames_dir}'.")

    # First run downloads the OCR model (a few seconds). lang='en' = English text.
    print("Loading PaddleOCR (first run downloads a small model)...")
    ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)

    rows = []
    for name in files:
        path = os.path.join(frames_dir, name)
        result = ocr.ocr(path, cls=True)
        # result is a list (one entry per image); each detection is [box, (text, confidence)]
        if result and result[0]:
            for line in result[0]:
                text = line[1][0]
                conf = round(float(line[1][1]), 3)
                rows.append({"frame": name, "text": text, "confidence": conf})
        print(f"  {name}: {len(result[0]) if result and result[0] else 0} text region(s)")

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["frame", "text", "confidence"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone. {len(rows)} text reads -> {out_csv}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read on-screen text from frames with PaddleOCR.")
    parser.add_argument("--frames", default="frames", help="Folder with extracted frames")
    parser.add_argument("--out", default="ocr_text.csv", help="Output CSV file")
    args = parser.parse_args()
    run_ocr(args.frames, args.out)
