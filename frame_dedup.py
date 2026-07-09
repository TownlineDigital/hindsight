"""
FRAME DE-DUPLICATION - a free, local (no API call) filter that drops frames
nearly identical to the last KEPT frame, before they're ever sent to Gemini.

Why this matters for cost: a static screen (a long dialogue box, a paused
moment, a slow-panning menu) sampled at a fixed rate (analyze_matches.py's
--battle-fps) can easily produce several back-to-back frames that differ only
in video-compression noise. Each one costs the same input tokens as a frame
with real new information, even though it can't contain any event the
previous frame didn't already show. Cutting these before they reach Gemini
reduces the single biggest cost driver in the whole pipeline (bulk per-match
battle-frame event extraction - see ARCHITECTURE_HANDOFF.md section 2/2a)
with NO accuracy loss - if anything, it removes a source of noisy/conflicting
field_state reads on frames with nothing new to report.

Deliberately simple: a coarse grayscale-downscale pixel-difference check via
OpenCV (already a project dependency), not a fancy perceptual hash or ML
model. "Is this frame meaningfully different from the last KEPT one" doesn't
need to be sophisticated to be reliable, and a simple, fast, easily-tested
check is much easier to trust than a black-box one.
"""

import cv2
import numpy as np


def frame_difference_score(path_a, path_b, compare_size=64):
    """0.0 = identical, higher = more different. Downscales both frames to a
    tiny compare_size x compare_size grayscale image first - deliberately
    coarse, so it's fast AND robust to compression-noise-level differences
    that don't reflect a real on-screen change (a full-resolution pixel diff
    would flag those as "different" too, defeating the purpose). Returns
    +inf (never a duplicate) if either image can't be read, so a corrupt/
    unreadable frame is always kept rather than silently dropped."""
    a = cv2.imread(path_a, cv2.IMREAD_GRAYSCALE)
    b = cv2.imread(path_b, cv2.IMREAD_GRAYSCALE)
    if a is None or b is None:
        return float("inf")
    a = cv2.resize(a, (compare_size, compare_size), interpolation=cv2.INTER_AREA)
    b = cv2.resize(b, (compare_size, compare_size), interpolation=cv2.INTER_AREA)
    return float(np.mean(cv2.absdiff(a, b)))


def dedupe_frames(frames, threshold=2.0, compare_size=64):
    """frames: [(path, timestamp), ...] in chronological order - the exact
    shape analyze_matches.sample_window() returns. Returns the subset to
    actually send to Gemini.

    Always keeps the first frame. A later frame is kept only if it differs
    enough from the last KEPT frame (not merely the previous frame in the
    list) - this is what collapses a long run of near-identical frames (a
    slow fade, a paused screen held for several sample intervals) down to
    ONE kept frame instead of one kept frame per tiny incremental step, which
    a "differs from the immediately previous frame" check would miss.

    threshold=0 disables de-duplication entirely (keeps every frame) - useful
    for comparing behavior with/without this filter."""
    if not frames or threshold <= 0:
        return list(frames)
    kept = [frames[0]]
    for path, ts in frames[1:]:
        last_kept_path = kept[-1][0]
        if frame_difference_score(last_kept_path, path, compare_size) >= threshold:
            kept.append((path, ts))
    return kept
