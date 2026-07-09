"""
Free, local (no API call, no OCR) HP-percent reader via direct pixel-color
measurement of the on-screen HP bar - a cross-check/backstop for
ocr_battle_reader.py's read_name_hp_plate(), which reads the printed "94%"
or "155/155" TEXT next to the bar. This module ignores the text entirely
and instead measures how much of the bar's fixed-width track is filled
with bar-color (green/yellow/red) versus empty/background - the same
information the text is printed for, read a completely different way.

Why this is worth having alongside OCR, not instead of it: the HP bar
render is deterministic pixel data (a game always draws it the same way
for a given HP fraction) with no font-rendering or compression-artifact
ambiguity the way small printed digits can have. When OCR's digit read and
this pixel read agree, that is a strong accuracy signal ("two independent
methods reached the same number"); when they disagree, that is itself a
useful flag - one of them mis-read - it's a case worth reporting as
low-confidence and falling back to a Gemini vision read for THAT moment,
not silently trusting either automatically.

HONEST CURRENT SCOPE - read this before trusting anything in here. This
was actually run against a real frame during development (not just
written and assumed to work) - here's exactly what that testing found:
  - The region below (OPPONENT_TOP_RIGHT_HP_BAR) was measured from ONE
    real captured frame - jobs/3e46bb33364c/match_frames/match_2/b_00021.jpg
    - a Hydreigon plate reading 94% HP (per its on-screen text) - for the
    single Pokemon-plate position that appears at top-right of the
    broadcast overlay. A doubles battle can show FOUR such plates at once
    (two per side); the other three positions have NOT been measured/
    validated against real footage yet. Do not assume they share the same
    fractional coordinates by symmetry - measure each one from a real
    frame the same way, exactly the caveat ocr_battle_reader.py's
    NAME_PLATE_VALIDATED already states for the text-reading side of this
    same problem.
  - IMPORTANT lesson from that testing: the first-cut region included the
    "94%" TEXT LABEL that sits to the right of the actual bar graphic -
    that text is not part of the fill, and reading it as if it were bar
    pixels broke the column scan entirely (read back 0%). The region below
    stops BEFORE the text label. If a different plate position's text sits
    somewhere else relative to its bar, re-check for the same trap.
  - Precision is limited by source resolution, honestly: at the pipeline's
    640x360 battle-sampling resolution, the bar's fillable track is only
    ~45-50 pixels wide, so each pixel is worth roughly 2 percentage
    points. Tested against the real 94%-HP frame, this reads back ~100%
    (rounds to "basically full," within the +/-8-point tolerance
    cross_check_hp() uses by default, but not exact). Treat this as a
    coarse cross-check that catches GROSS OCR errors (e.g. OCR misreading
    "94%" as "9%"), not a precise replacement for the text reading. It
    would very likely be meaningfully more precise fed the pipeline's
    higher-res OCR-pass frames (1280px wide, see ocr_pipeline.py) instead
    of the 640px battle-sampling frames - that combination has NOT been
    tested yet.
  - Only tested at one HP value (94%, i.e. a mostly-full, all-green bar).
    The yellow/red hue bands are standard-game-UI-palette assumptions,
    unconfirmed against any real mid/low-HP frame - test against a real
    frame in each color range before trusting those two bands
    specifically.
  - Saturation/value minimums were calibrated DOWN from an initial 80/80
    to 50/60 against real footage - the bar's rounded left edge has a
    couple of genuinely anti-aliased (softer-colored) pixels that 80/80
    rejected as "empty," undercounting the real fill. This is the kind of
    thing that only shows up by testing against a real frame, not by
    reasoning about it - see ocr_battle_reader.py's docstring for the same
    lesson learned on OCR preprocessing.

  - 2026-07-05 addition: SINGLE_ACTIVE_HP_BAR_SLOT1 / SLOT2, for an
    ENTIRELY DIFFERENT broadcast layout found in jobs/303d13ba0940 (a
    console-native "Pokemon Champions" HUD, not the Showdown-style overlay
    OPPONENT_TOP_RIGHT_HP_BAR/PLAYER_BOTTOM_LEFT_HP_BAR above came from).
    That job shows the PLAYER's own two active Pokemon as two adjacent
    plates at the bottom of the screen, each with its own HP bar with the
    "current/max" HP number rendered DIRECTLY ON TOP of the bar (not off
    to the side) - confirmed to need its own region calibration entirely;
    trying the two regions above against this job's frames read back 0.0
    or 1.0 regardless of true HP (confirmed by direct testing, not
    assumed), because the two jobs' HP-plate layouts share nothing in
    common pixel-position-wise.

    Calibrated + tested against THREE real frames with known ground-truth
    HP (from that job's own events.csv, cross-checked visually against the
    actual frame before trusting the csv value):
      - match_2/b_00050.jpg: Floette 156/156 (100%, slot 1) -> reads 93.8%.
      - match_2/b_00050.jpg: Incineroar 131/200 (65.5%, slot 2) -> reads
        68.8%.
      - match_2/b_00019.jpg: Altaria 16/182 (8.8%, slot 2, RED bar) ->
        reads 8.6% - confirms the red band works for this HUD too.
      These three are close (within ~3-4 points), genuinely validated.

    IMPORTANT DISCOVERED LIMITATION, found by testing a FOURTH real frame
    rather than declaring victory after three good ones:
      - match_2/b_00117.jpg: Palafin 161/207 (77.8%, slot 1) -> reads back
        only 19.8% - badly wrong. Root cause, confirmed by direct HSV
        pixel inspection rather than guessed at: this particular frame is
        noticeably DARKER overall (fill pixels top out around
        Value~80-84 in this frame, vs ~200-255 in the three frames above),
        so the same fixed v_min=60 brightness cutoff in _COLOR_BANDS -
        which the three frames above clear easily - fails partway through
        this darker frame's true fill and cuts the contiguous-run scan
        short. This is a MORE fundamental problem than a region-position
        miscalibration: unlike the fixed-overlay job the original two
        regions were measured from, this job is a real Twitch VOD whose
        scene brightness/exposure varies frame-to-frame (lighting effects,
        stream encoding, etc.), so a single fixed absolute-V threshold
        cannot be trusted across this job's full frame set. A real fix
        would need per-frame brightness normalization or a relative
        (percentile-of-this-frame rather than fixed-absolute) fill/empty
        threshold - NOT attempted here, since shipping an unverified "fix"
        for this would violate this module's own "don't guess" standard
        and there wasn't time this pass to validate one properly.

    Bottom line: treat SINGLE_ACTIVE_HP_BAR_SLOT1/2 as validated ONLY for
    well-lit frames similar to the three source frames above, NOT as
    reliable across this job's (or any other new job's) full, variously-lit
    frame set. A caller integrating this should prefer cross_check_hp's
    agree=False signal over trusting a lone pixel read blindly, exactly as
    already designed - this limitation is a strong argument for actually
    using that cross-check rather than a reason to skip it.
"""

import cv2
import numpy as np

# Fractional (top, bottom, left, right) crop of the FULL frame covering the
# HP bar's fill graphic ONLY - deliberately stops short of the "94%" text
# label that sits to its right (see module docstring). Re-measure per
# plate position from a real frame; do not assume symmetry.
OPPONENT_TOP_RIGHT_HP_BAR = (0.095, 0.150, 0.840, 0.916)

# Player's OWN plate (bottom-left of the broadcast overlay). Measured from
# real footage the same way the opponent region was - NOT assumed by
# symmetry (the two plates have different internal layouts: the player's HP
# fill sits BELOW its name bar with the "157/157"-style HP text overlaid on
# the fill's right half, whereas the opponent's text sits to the RIGHT of
# the bar). Fill-track columns were found by an HSV green-band scan of a
# real frame (fill runs x=54..134 at 640px width), then the left bound was
# tightened to exclude ~8px of bluish plate edge that a first cut wrongly
# included (which broke the left-to-right fill scan and read back 0% - the
# same class of "region accidentally included non-bar pixels" bug the
# opponent region hit with its text label).
#
# VALIDATED at TWO real HP values (not just full):
#   - jobs/3e46bb33364c/match_frames/match_2/b_00021.jpg: Rotom 157/157
#     (100%) -> reads 100%, cross_check agree=True.
#   - .../b_00047.jpg: Rotom 69/157 (= 44% by the on-screen text) -> reads
#     51%, cross_check agree=True (within the default +/-8 tolerance). Off
#     by ~7 points - consistent with the honest ~1-2 HP%/pixel precision
#     cap on 640x360 frames documented above; a coarse gross-error catch,
#     not an exact read.
PLAYER_BOTTOM_LEFT_HP_BAR = (0.914, 0.950, 0.084, 0.211)

# jobs/303d13ba0940's doubles-active-slot HUD (a different broadcast/game
# overlay entirely - see module docstring's 2026-07-05 addition for the
# full validation story, including a discovered brightness-variance
# limitation that means these two are NOT reliable across this job's
# whole, variously-lit frame set - only for well-lit frames like the ones
# these were measured/tested against).
SINGLE_ACTIVE_HP_BAR_SLOT1 = (306 / 360, 317 / 360, 59 / 640, 140 / 640)
SINGLE_ACTIVE_HP_BAR_SLOT2 = (306 / 360, 317 / 360, 190 / 640, 283 / 640)

# HONEST CROSS-FRAME CAVEAT found while validating the above (applies to
# BOTH plate regions): the broadcast overlay's plates are NOT pinned to a
# fixed pixel row across every frame. Re-testing the OPPONENT region on
# b_00047 (Scrafty, 71% by text) read back 0%, because that frame's
# top-right bar sits ~8px LOWER (abs y~37-65) than it does in b_00021
# (abs y~34-54) and is partly yellow - the fixed OPPONENT region row window
# misses it. So these fractional regions are validated for the plate
# LAYOUT/position they were measured against, and a real integration should
# either (a) locate the plate first (e.g. via icon_template_matcher on a
# plate-anchor sprite) then read the bar relative to it, or (b) widen the
# region's vertical window and accept a bit more noise. Documented here
# rather than silently trusting a single-frame measurement.

# HSV hue bands (OpenCV's 0-179 hue range) for each bar-fill color, plus
# minimum saturation/value to count as "confidently colored" rather than a
# dim/background pixel. Only the green band is actually confirmed against
# a real frame so far (see docstring).
_COLOR_BANDS = {
    "green":  ((35, 85),  50, 60),
    "yellow": ((20, 35),  50, 60),
    "red_lo": ((0, 10),   50, 60),
    "red_hi": ((170, 179), 50, 60),
}


def _is_filled_pixel(h, s, v):
    for _name, ((lo, hi), s_min, v_min) in _COLOR_BANDS.items():
        if lo <= h <= hi and s >= s_min and v >= v_min:
            return True
    return False


def _crop(frame, region):
    h, w = frame.shape[:2]
    top, bottom, left, right = region
    return frame[int(h * top):int(h * bottom), int(w * left):int(w * right)]


def hp_fraction_from_bar(frame_bgr, region=OPPONENT_TOP_RIGHT_HP_BAR, min_columns=6):
    """Returns a float 0.0-1.0 estimating HP fraction from bar-fill pixel
    color, or None if the crop is too small/degenerate to read confidently
    (fewer than `min_columns` pixel-columns available - a corrupt or
    mis-cropped frame, not a real 0% HP reading, which would still have a
    real-width empty bar to measure). Treat None as "no reading," not "0
    HP" - a caller should keep whatever OCR/vision value it already has
    rather than overwrite it with a false zero.

    Method: for each pixel-column left-to-right, takes the median HSV pixel
    down that column's height (robust to a stray highlight/shadow pixel
    that a single-row sample could catch) and classifies it filled/empty
    via _is_filled_pixel. Since the game always fills the bar from the
    left, the read fraction is the length of the CONTIGUOUS filled run
    starting at column 0 (tolerating a couple of noisy/anti-aliased
    columns via gap_tolerance), divided by total columns.
    """
    crop = _crop(frame_bgr, region)
    if crop is None or crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    height, width = hsv.shape[:2]
    if width < min_columns:
        return None

    filled_run = 0
    gap_tolerance = max(1, width // 40)
    gap = 0
    for x in range(width):
        col = hsv[:, x, :]
        med_h, med_s, med_v = (int(np.median(col[:, i])) for i in range(3))
        if _is_filled_pixel(med_h, med_s, med_v):
            filled_run += 1 + gap  # count the tolerated gap as filled too
            gap = 0
        else:
            gap += 1
            if gap > gap_tolerance:
                break

    return round(filled_run / width, 3)


def cross_check_hp(ocr_hp_percent, pixel_hp_fraction, agree_tolerance=8):
    """Compares an OCR-derived HP percent (0-100, or None) against this
    module's pixel-derived fraction (0.0-1.0, or None) and returns a dict:
    {"value": <best percent to use>, "agree": bool or None, "source": str}.
    - Both present and within `agree_tolerance` percentage points: high
      confidence, returns the OCR value (text is more precise - exact
      digits - when the two independent reads agree) tagged agree=True.
    - Both present but disagree beyond tolerance: returns the OCR value
      but tagged agree=False - callers should treat this event as
      lower-confidence and consider a Gemini vision read for that moment,
      the same "flag, don't force a guess" pattern used elsewhere in this
      pipeline (see pokemon_identity.py, ocr_battle_reader.py).
    - Only one present: returns whichever exists, agree=None (nothing to
      cross-check against).
    - Neither present: returns {"value": None, "agree": None, "source": "none"}.
    """
    pixel_percent = None if pixel_hp_fraction is None else round(pixel_hp_fraction * 100)

    if ocr_hp_percent is not None and pixel_percent is not None:
        agree = abs(ocr_hp_percent - pixel_percent) <= agree_tolerance
        return {"value": ocr_hp_percent, "agree": agree, "source": "ocr+pixel"}
    if ocr_hp_percent is not None:
        return {"value": ocr_hp_percent, "agree": None, "source": "ocr"}
    if pixel_percent is not None:
        return {"value": pixel_percent, "agree": None, "source": "pixel"}
    return {"value": None, "agree": None, "source": "none"}
