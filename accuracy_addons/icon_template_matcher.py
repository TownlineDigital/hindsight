"""
Free, local (no API call) icon detection via OpenCV template matching -
the "does this exact fixed graphic appear in this frame" counterpart to
ocr_battle_reader.py's text reading. Targets UI elements that are always
the SAME sprite regardless of context (move-type icons, status-condition
icons, weather/terrain banners, the Tera crown) - a vision-model call is
overkill for "is this literally the same 24x24 graphic as last time,"
and template matching is both free and immune to the kind of
misread/hallucination risk a vision call has on a small icon.

TESTED against real captured frames during development (not just written
and assumed to work) - jobs/3e46bb33364c/match_frames/match_2/b_00021.jpg,
the frame the original 3 move-type templates below were extracted from.
Re-matching each template back against its own source frame scored 1.000
(perfect) at the correct on-screen location for all three, which confirms
the crop -> grayscale -> matchTemplate -> threshold -> location-math
pipeline itself is correct. That is a "does the plumbing work" test, not a
"does this generalize to a different frame/lighting/background" test - see
scope notes below for what that next step would need (and see the
2026-07-05 addition below for what generalization testing actually found).

HONEST CURRENT SCOPE - read this before trusting anything in here:
  - SEVEN move-type templates and ONE status template are now included and
    validated against real footage:
      * type_water, type_fire, type_electric - extracted from the Move Info
        panel of jobs/3e46bb33364c/match_frames/match_2/b_00021.jpg;
        validated by self-match (1.000) only.
      * type_grass, type_ice, type_dark (added 2026-07-05) - extracted from
        the SAME job's match_1/b_00021.jpg (a different match's Move Info
        panel, showing Flower Trick/Triple Axel/Knock Off/Thunder Punch).
        Self-match scores 1.000 at the source location. Cross-frame testing
        against every other frame in both matches of that job found no
        genuine additional occurrence of grass/ice/dark to confirm true-
        positive generalization (this job's other panels don't happen to
        show those types again) - so, same as the original 3, these are
        currently self-match-validated only, not cross-frame-validated the
        way burn is.
      * burn (status badge, in templates/status/status_burn.png) - the flame
        badge that sits on a burned Pokemon's HP name-plate, cropped 18x18
        from the top-right plate of the SAME real frame (b_00021, a
        Will-O-Wisp'd Hydreigon). This one is validated MORE thoroughly than
        the move-type templates: besides self-matching its source frame at
        1.000, it was run against all 38 battle frames of that match and
        scored 0.94-0.98 on the 10 OTHER frames where the burn badge is
        present, vs 0.30-0.43 where it isn't - real cross-frame
        generalization with clean separation, not just a self-match.
        (Registered in VALIDATED_STATUS_TEMPLATES; load via
        load_status_templates() / identify_status_icon().)
  - A REAL FALSE-POSITIVE was found and fixed while validating the 2026-07-05
    additions - worth recording here since it's a genuine limitation of
    plain grayscale template matching, not a hypothetical one. The new
    "ice" template (cyan/light-blue) scored 0.96 - well above
    DEFAULT_THRESHOLD - against the ELECTRIC-type ("Discharge", yellow) row
    of a completely different frame
    (jobs/3e46bb33364c/match_frames/match_2/b_00014.jpg), because
    cv2.matchTemplate on a GRAYSCALE image only compares luminance/shape,
    not color - two icons that are similarly-shaped rounded badges with a
    white symbol can score deceptively high against each other regardless
    of hue. Fix: `identify_move_type_icon`/`identify_status_icon` now cross-
    check the matched region's actual median HUE (from the real color
    frame) against that icon's own expected hue (`_TYPE_HUE`/`_STATUS_HUE`,
    each measured from the real footage the template itself came from) and
    reject a candidate whose region hue is more than HUE_TOLERANCE away -
    this rejects the ice-vs-electric false positive above (hue 108 vs 25,
    an 83-point gap) while still accepting the genuine self-match (hue
    difference 0). IMPORTANT remaining limitation, found by the same
    measurement: water and ice happen to measure the SAME median hue (108)
    against this game's actual color palette (both are cyan/pale-blue) - the
    hue gate does NOT and CANNOT distinguish water from ice from hue alone.
    Do not trust `identify_move_type_icon` to tell water and ice apart;
    treat a "water" or "ice" result as "one of these two, hue-consistent
    with both" until a saturation/value or region-shape refinement is
    built and validated the same rigorous way. This is exactly the kind of
    thing that only shows up by testing against a real, different frame -
    see ocr_battle_reader.py's docstring for the same lesson learned on OCR
    preprocessing.
  - The other 11 move types, the other status-condition icons (par/psn/tox/
    slp/frz/confusion), weather/terrain banners, and the Tera crown are
    NOT included yet. Do not assume they work - they need the same
    real-footage extraction process before being trusted, the same way
    ocr_battle_reader.py's NAME_PLATE_VALIDATED explicitly documents which
    plate position is/isn't confirmed. Adding one is cheap (crop a clean
    example from a real frame, drop it in templates/, one line to register
    it, measure its hue for the gate) but each one needs its own real-frame
    validation - don't bulk-add guessed/generated icon images and assume
    they'll match the actual in-game sprite pixel-for-pixel. (Note: this
    project's current format has Terastallization OFF, so a Tera crown
    likely never appears in real footage here - none was found in the
    frames reviewed for the burn badge.)
  - Matching is scale-sensitive: cv2.matchTemplate finds the template at
    the SAME size it was captured at. These templates were extracted from
    native 640x360 frames (the resolution analyze_matches.py samples
    battle frames at). If fed a differently-scaled frame (e.g.
    ocr_pipeline.py's 1280px-wide OCR pass), matches will likely fail or
    score low - re-extract templates at that resolution, or downscale the
    input frame's search region to 640-width-equivalent before matching.
    This module does NOT do multi-scale search (deliberately - slower,
    adds false-positive risk; better to match template and frame
    resolution deliberately).
  - Not wired into ocr_pipeline.py or analyze_matches.py yet. This is a
    standalone module ready to be integrated, kept separate so it can be
    reviewed/tested on its own without touching the live pipeline files
    (see accuracy_addons/README.md for integration notes).
  - identify_move_type_icon() with region=None searches the WHOLE frame,
    which is NOT the intended real usage - a busy real frame can
    legitimately contain more than one of the 3 known icons at once (e.g.
    a Move Info panel listing 4 different moves), so a whole-frame search
    can only tell you "one of my known icons is SOMEWHERE in this frame,"
    not which move it belongs to. Real usage should always pass `region`
    narrowed to one specific icon's on-screen slot (e.g. one move row).
"""

import os

import cv2
import numpy as np

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates", "move_types")
STATUS_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates", "status")

# name -> filename. Only add an entry here once a real-footage-extracted
# template file actually exists for it (see module docstring).
VALIDATED_TEMPLATES = {
    "water": "type_water.png",
    "fire": "type_fire.png",
    "electric": "type_electric.png",
    "grass": "type_grass.png",
    "ice": "type_ice.png",
    "dark": "type_dark.png",
}

# Expected median HUE (OpenCV's 0-179 range) for each validated move-type
# icon, measured directly from the real frame each template was extracted
# from (masking to saturation>60, 60<value<235 pixels to avoid the white
# symbol/near-black background skewing the median - see module docstring's
# 2026-07-05 false-positive finding for why this check exists at all).
# water and ice measure the SAME hue (108) - see docstring, this gate
# cannot and does not claim to tell those two apart.
_TYPE_HUE = {
    "water": 108,
    "fire": 176,
    "electric": 25,
    "grass": 54,
    "ice": 108,
    "dark": 126,
}
HUE_TOLERANCE = 20  # max acceptable |hue difference| (circular) before a candidate match is rejected

# Status-condition badges that sit on a Pokemon's HP name-plate (the small
# circular icon above/left of the name - e.g. the flame badge for burn).
# Same rule as VALIDATED_TEMPLATES: only add an entry once a real-footage-
# extracted, self-match-validated template file actually exists for it.
#
# "burn": status_burn.png - cropped (18x18) from the top-right opponent
#   plate of jobs/3e46bb33364c/match_frames/match_2/b_00021.jpg (Hydreigon,
#   burned by Will-O-Wisp earlier in that match). This one has been tested
#   MORE than the 3 move-type templates above: besides self-matching its own
#   source frame at 1.000, it was run against all 38 battle frames in that
#   match and scored 0.94-0.98 on the 10 OTHER frames where Hydreigon's
#   plate still shows the burn badge, vs 0.30-0.43 on the frames where it
#   doesn't - i.e. it actually generalizes across frames with clean
#   separation, not just self-matches. See tests/ note in the module
#   docstring and accuracy_addons/README.md for the quoted per-frame scores.
VALIDATED_STATUS_TEMPLATES = {
    "burn": "status_burn.png",
}

# Same idea as _TYPE_HUE, for status badges - see HUE_TOLERANCE/the
# 2026-07-05 false-positive docstring section.
_STATUS_HUE = {
    "burn": 136,
}

DEFAULT_THRESHOLD = 0.75  # TM_CCOEFF_NORMED score; the 3 validated templates
# re-matched against their own source frame at 1.000 (see docstring) - not
# yet stress-tested against DIFFERENT frames showing the same icon under
# different lighting/backgrounds, so treat borderline scores (0.75-0.85)
# with some skepticism until that's done.


def load_templates(names=None, registry=None, templates_dir=None):
    """Loads template images (grayscale, for matching) into a dict:
    name -> numpy array. `names` restricts to a subset of the registry;
    None loads all entries in the registry. `registry` (name->filename) and
    `templates_dir` default to the move-type set (VALIDATED_TEMPLATES /
    TEMPLATES_DIR) for backward compatibility - pass VALIDATED_STATUS_TEMPLATES
    / STATUS_TEMPLATES_DIR (or use load_status_templates) for status badges.
    Skips (with a printed warning, not a crash) any name whose file doesn't
    actually exist on disk, since a partially-populated templates/ folder is
    the expected normal state right now, not an error."""
    registry = registry if registry is not None else VALIDATED_TEMPLATES
    templates_dir = templates_dir if templates_dir is not None else TEMPLATES_DIR
    names = names or list(registry.keys())
    out = {}
    for name in names:
        filename = registry.get(name)
        if not filename:
            print(f"[icon_template_matcher] no registered template for '{name}', skipping")
            continue
        path = os.path.join(templates_dir, filename)
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            print(f"[icon_template_matcher] template file missing/unreadable: {path}")
            continue
        out[name] = img
    return out


def load_status_templates(names=None):
    """Convenience wrapper: loads the validated status-badge templates
    (VALIDATED_STATUS_TEMPLATES from templates/status/). Same skip-missing
    behavior as load_templates. Currently only "burn" is validated - see the
    VALIDATED_STATUS_TEMPLATES comment for exactly how it was tested."""
    return load_templates(names, registry=VALIDATED_STATUS_TEMPLATES,
                          templates_dir=STATUS_TEMPLATES_DIR)


def _median_hue(frame_bgr, top_left, shape):
    """Median HSV hue (0-179) of the `shape`-sized region of `frame_bgr`
    starting at `top_left` - masked to saturation>60, 60<value<235 pixels
    (same band used to measure each template's own _TYPE_HUE/_STATUS_HUE
    entry) so a near-white symbol or near-black background pixel doesn't
    skew the read. Returns None if the region has no pixels passing that
    mask (e.g. an all-dark/degenerate crop) - callers must treat that as
    "can't verify," not "hue 0"."""
    x, y = top_left
    th, tw = shape[:2]
    crop = frame_bgr[y:y + th, x:x + tw]
    if crop is None or crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    mask = (s > 60) & (v > 60) & (v < 235)
    if not mask.any():
        return None
    return float(np.median(h[mask]))


def _hue_close(measured_hue, expected_hue, tolerance=HUE_TOLERANCE):
    """True if `measured_hue` is within `tolerance` of `expected_hue`,
    accounting for hue's circular wraparound at 179/0 (OpenCV's hue range).
    `measured_hue` of None (couldn't be read - see _median_hue) is treated
    as "can't verify, don't reject" - a missing color read shouldn't by
    itself veto an otherwise-good shape match, since the whole point of
    this gate is catching a WRONG-colored match, not adding a new way to
    silently drop a right one."""
    if measured_hue is None or expected_hue is None:
        return True
    diff = abs(measured_hue - expected_hue)
    return min(diff, 180 - diff) <= tolerance


def identify_status_icon(frame_bgr, region=None, threshold=DEFAULT_THRESHOLD):
    """Tries every validated status-badge template against `frame_bgr` (or
    `region` of it) and returns the best-scoring status name whose score
    clears `threshold`, or None if nothing matched confidently. Same shape
    and caveats as identify_move_type_icon (ALWAYS pass a `region` narrowed
    to the plate whose status you want in real usage - a doubles battle
    shows up to four plates, and a whole-frame search can't tell you WHICH
    Pokemon a matched badge belongs to). Only "burn" can currently be
    recognized (see VALIDATED_STATUS_TEMPLATES) - any other status just
    returns None, not a wrong guess.

    A shape/luminance match is additionally cross-checked against the
    matched region's actual HUE (see _STATUS_HUE/_hue_close and the module
    docstring's 2026-07-05 false-positive finding) - a high-scoring but
    wrong-colored candidate is rejected rather than returned."""
    templates = load_status_templates()
    best_name, best_score = None, 0.0
    for name, template in templates.items():
        if region is not None:
            found, score, loc = match_icon_in_region(frame_bgr, template, region, threshold)
        else:
            found, score, loc = match_icon(frame_bgr, template, threshold)
        if not found or score <= best_score:
            continue
        if loc is not None and not _hue_close(_median_hue(frame_bgr, loc, template.shape), _STATUS_HUE.get(name)):
            continue
        best_name, best_score = name, score
    return best_name


def match_icon(frame_bgr, template_gray, threshold=DEFAULT_THRESHOLD):
    """Searches for `template_gray` anywhere in `frame_bgr` (a full frame or
    an already-cropped region - see match_icon_in_region for the latter).
    Returns (found: bool, score: float, top_left: (x, y) or None). A single
    fixed-scale match via cv2.TM_CCOEFF_NORMED - see module docstring's
    scale-sensitivity caveat before feeding this a frame at a different
    resolution than the template was captured at."""
    if frame_bgr is None or template_gray is None:
        return False, 0.0, None
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    th, tw = template_gray.shape[:2]
    if gray.shape[0] < th or gray.shape[1] < tw:
        return False, 0.0, None
    result = cv2.matchTemplate(gray, template_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    return max_val >= threshold, float(max_val), max_loc


def match_icon_in_region(frame_bgr, template_gray, region, threshold=DEFAULT_THRESHOLD):
    """Same as match_icon, but only searches within `region` - a fractional
    (top, bottom, left, right) crop of the full frame, the same convention
    ocr_battle_reader.py's BOTTOM_BANNER_REGION/NAME_PLATE_VALIDATED use.
    Restricting the search area is faster and reduces false-positive risk
    from a coincidentally-similar patch elsewhere in the frame. No region
    validated/shipped yet for move-type icons specifically - the Move Info
    panel's per-row position needs to be measured from real footage the
    same way the HP-plate regions were, before a caller should hardcode
    one here as trusted."""
    h, w = frame_bgr.shape[:2]
    top, bottom, left, right = region
    crop = frame_bgr[int(h * top):int(h * bottom), int(w * left):int(w * right)]
    found, score, loc = match_icon(crop, template_gray, threshold)
    if loc is not None:
        loc = (loc[0] + int(w * left), loc[1] + int(h * top))
    return found, score, loc


def identify_move_type_icon(frame_bgr, region=None, threshold=DEFAULT_THRESHOLD):
    """Tries every validated move-type template against `frame_bgr` (or
    `region` of it, if given) and returns the best-scoring type name whose
    score clears `threshold`, or None if nothing matched confidently.
    Convenience wrapper over match_icon/match_icon_in_region - e.g.
    identifying a move's type from its icon rather than needing a vision
    call or a full movedex lookup by name. Only water/fire/electric/grass/
    ice/dark can currently be recognized this way (see module docstring,
    including the water-vs-ice hue-ambiguity caveat) - a real icon of any
    other type will simply return None, not a wrong guess. ALWAYS pass a
    `region` narrowed to one icon's slot in real usage - see docstring's
    whole-frame-search caveat.

    A shape/luminance match is additionally cross-checked against the
    matched region's actual HUE (see _TYPE_HUE/_hue_close and the module
    docstring's 2026-07-05 false-positive finding - the "ice" template
    scoring 0.96 against an electric-colored region in a different frame
    is exactly the case this rejects) - a high-scoring but wrong-colored
    candidate is rejected rather than returned."""
    templates = load_templates()
    best_name, best_score = None, 0.0
    for name, template in templates.items():
        if region is not None:
            found, score, loc = match_icon_in_region(frame_bgr, template, region, threshold)
        else:
            found, score, loc = match_icon(frame_bgr, template, threshold)
        if not found or score <= best_score:
            continue
        if loc is not None and not _hue_close(_median_hue(frame_bgr, loc, template.shape), _TYPE_HUE.get(name)):
            continue
        best_name, best_score = name, score
    return best_name
