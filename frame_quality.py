"""
FRAME QUALITY SELECTION - a free, local (no API call) sharpness score used to
pick the BEST nearby sampled frame for something (an event's reference photo,
a pixel cross-check target), instead of just whichever frame happens to be
closest in time.

Why this matters: analyze_matches.attach_reference_frames() used to always
pick the single nearest-in-time sampled frame for every event, with no check
for whether that particular frame was mid-animation/transition (a flash, a
slide-in, a partially rendered frame) - which matters twice over: once for
the human-reviewable "reference photo" shown in the dashboard, and again for
every free accuracy_addons pixel cross-check that reads pixels straight from
that image (hp_bar_reader, icon_template_matcher's burn check, the OCR-
visibility check) - a blurry/transitional frame quietly degrades all of them,
without ever spending an extra Gemini call to notice.

Deliberately simple and fast, same philosophy as frame_dedup.py (this
project's other free/local frame-selection module): Laplacian variance
(`cv2.Laplacian(gray, cv2.CV_64F).var()`) is a standard, well-known sharpness
proxy - a sharp, high-detail image has more high-frequency edge content and
therefore a higher second-derivative variance; a blurry/flat/transitional
frame has less. Not a fancy perceptual model, just a fast, easily-tested
pixel computation - the same "doesn't need to be sophisticated to be
reliable" reasoning frame_dedup.py's own docstring makes for its pixel-diff
check.

HONEST SCOPE: sharpness alone can't distinguish "mid-transition and
therefore genuinely uninformative" from "sharp but simply showing the wrong
moment" (e.g. a crisp frame from a second before the event actually
happened) - it is a QUALITY signal among otherwise-similarly-timed
candidates, not a replacement for choosing a reasonable time window first.
See analyze_matches.attach_reference_frames' own docstring for how the two
are combined: candidates are gathered by TIME window first, then ranked by
sharpness only among those already-close candidates.
"""

import cv2


def frame_sharpness(path):
    """Returns a Laplacian-variance sharpness score for the image at `path`
    (higher = sharper), or None if the file can't be read - callers should
    treat None as "unusable," never as a valid (e.g. 0.0) score, so a
    missing/corrupt frame is never mistaken for the sharpest option."""
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    return float(cv2.Laplacian(img, cv2.CV_64F).var())


def pick_sharpest(paths):
    """Returns whichever path in `paths` scores highest via frame_sharpness(),
    skipping any that can't be read. Returns None if `paths` is empty or
    every path in it is unreadable."""
    best_path, best_score = None, None
    for p in paths:
        score = frame_sharpness(p)
        if score is None:
            continue
        if best_score is None or score > best_score:
            best_path, best_score = p, score
    return best_path
