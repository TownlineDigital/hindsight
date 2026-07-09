"""
Free, local (no API call) SPECIES identification via OpenCV template
matching against the reference sprite library fetched by
tools/fetch_species_sprites.py (accuracy_addons/templates/species/) - the
"deeper version" fix noted in ARCHITECTURE_HANDOFF.md sections 2g/2h/2i:
an attempt at a real local icon-matcher against this game's closed
~212-species roster, targeting the opponent's team-preview icon column
specifically, since that's the dominant source of roster-read error (icons
only, no name text, unlike the player's own fully-labeled side).

READ THIS FIRST - HONEST HEADLINE RESULT: real validation against a real
frame (see HONEST CURRENT SCOPE below for the full story) found this
approach correctly identifies only about 1 of 6 real opponent sprites
(~17%) even after fixing a real crop-framing bug and adding a real
tight-cropping improvement. THIS IS NOT YET A RELIABLE SIGNAL. It is NOT
wired into analyze_matches.py/read_roster() - do not wire it in without
either a materially better real-footage result or a different underlying
approach (see "WHY IT DOESN'T WORK WELL YET" below for concrete next
ideas). This module is being kept and documented anyway because: (a) the
crop-framing bug it uncovered is real and now fixed regardless
(crop_opponent_sprite_column in analyze_matches.py), (b) the tight-crop
step is a real, measured improvement over the naive version (it turned one
row from a confidently WRONG answer into a confidently correct one) and is
useful infrastructure for whatever approach replaces the matching step
itself, and (c) this project's own culture is to document a real negative
result as honestly as a positive one, not quietly delete the attempt.

HOW IT WORKS:
  1. `slice_sprite_crops()` takes ONE already-cropped, already-zoomed
     opponent SPRITE column image (analyze_matches.crop_opponent_sprite_
     column's own output) and divides it into up to 6 per-Pokemon row
     bands, using row-position CONSTANTS measured directly from a real
     frame (see below).
  2. `_tight_crop_to_sprite()` then further crops each row band down to
     just the sprite's own silhouette, using a hue/brightness background
     mask (tuned to this game's magenta/maroon team-preview panel, same
     hue family as analyze_matches._ROSTER_PANEL_HUE_RANGE) plus a
     largest-connected-component bounding box - this matters because the
     reference PNGs are tightly cropped to their own sprite art with very
     little padding, while a row band straight out of slice_sprite_crops
     has the sprite sitting somewhere inside a much larger card with a
     lot of background around it; comparing those two directly (tested,
     see below) scores badly even for a genuinely correct match.
  3. `identify_species_icon()` compares one tight sprite crop against the
     reference library: each reference PNG (RGBA, transparent background)
     is alpha-composited onto a background color sampled from the crop,
     resized to a small fixed MATCH_SIZE, converted to grayscale, and
     compared via cv2.matchTemplate (TM_CCOEFF_NORMED).
  4. `identify_opponent_team_from_column()` / `merge_column_identifications()`
     tie the above together for one or more crops of the same match, with
     a MARGIN-based confidence gate - see the honest caveat about that gate
     below, though: it does not reliably work yet either.

HONEST CURRENT SCOPE - the real story, in order:
  - v1 of this module measured its row-slicing constants against a
    hand-rolled ad-hoc crop box that turned out to be WIDER than
    analyze_matches.py's actual production OPPONENT_COLUMN_BOX (that box
    is tuned for the type/gender BADGES icon_template_matcher reads, and
    deliberately excludes the sprite art itself). Running v1's real
    matching logic against the real production crop returned confidently
    WRONG top picks for every row (e.g. "altaria"/"pidgeot" for a row that
    was really Kingambit) - a real, found bug, not a tuning nit.
  - FIXED by adding a dedicated `crop_opponent_sprite_column()` +
    `OPPONENT_SPRITE_COLUMN_BOX` to analyze_matches.py, framed on the
    sprite art specifically, and re-measuring the row-divider constants
    below against ITS real output (jobs/8c10092ac4a9/vod.mp4, match 1,
    ~70s). A second false claim from v1 was also corrected while
    re-validating: v1 said the opponent's 6th Pokemon was "cut off by the
    source frame" - widening the crop box all the way to the bottom of
    the frame showed the real 6th Pokemon fully, undamaged; that was an
    artifact of an overly-tight ad-hoc crop, not a real screen-content
    limit.
  - Even with the CORRECTED crop, running the original (whole-row,
    untrimmed) matching approach against the real 6-row column returned
    only 1 of 6 rows above the confidence gate at all, and its top pick
    was WRONG (a Blastoise row was called "cofagrigus"). Investigating why
    found a real scale/framing mismatch: reference PNGs are tightly
    cropped to their own sprite (near-zero padding), while a raw row band
    has the actual sprite occupying maybe half its width/height, sitting
    in a large card - after both get resized to the same small MATCH_SIZE,
    the "same" sprite occupies very different fractions of the frame in
    each, which tanks a whole-image correlation score.
  - FIXED (partially) by adding `_tight_crop_to_sprite()` (see above) -
    this measurably helped: the Blastoise row went from a wrong top pick
    at 0.437 to a CORRECT top pick at 0.569 (clear margin over the
    runner-up). Real, checked, not assumed.
  - HOWEVER, re-running ALL 6 real rows through the tight-crop + matching
    pipeline together found only that ONE row (Blastoise) came back
    correct - 1/6 (~17%), not a usable accuracy rate. The other 5 rows'
    top picks were all wrong species entirely (not close misses), with
    scores in a similar 0.3-0.6 range as the correct one - meaning
    absolute score does NOT reliably separate right from wrong here.
  - The MARGIN-based confidence gate (top-1 vs top-2 score gap) - v1's
    proposed fix for the "absolute score is unreliable" problem - was
    RE-TESTED against this same real, corrected data and does NOT cleanly
    separate the one correct row from the wrong ones either: the correct
    Blastoise row's margin (0.037) is close to at least one WRONG row's
    margin (0.045 for a wrong "orthworm" pick) - so a reader relying on
    margin alone would sometimes accept a wrong answer and sometimes
    reject the one right answer, depending on where the threshold is set.
    This is a real, negative finding, not a threshold left untuned - it
    means the underlying per-candidate SCORE ITSELF isn't discriminative
    enough yet, and no amount of gate-tuning fixes that alone.
  - A silhouette/edge-based variant (Canny edges of the tight crop vs.
    Canny edges of each reference's alpha mask, correlated the same way)
    was also tried as a possible fix for the scale/background-sensitivity
    problem - it did WORSE (0/6 correct on the same real rows), so it was
    NOT adopted; grayscale intensity correlation (kept here) remains the
    better of the two tested approaches despite its own real limits.
  - WHY IT DOESN'T WORK WELL YET (concrete, not vague): (a) the
    background isn't a flat color - it has a visible gradient/highlight
    across the card, so a single-corner-pixel background sample and a
    simple hue/brightness mask only roughly separate sprite from
    background, and the connected-component step is sensitive to
    neighboring-row bleed and JPEG/compression noise near the row
    dividers; (b) real sprite art in this crop varies a lot in aspect
    ratio (tall/thin like Sneasler vs. wide like Blastoise) while the
    matching here doesn't correct for that beyond the tight crop itself,
    so a same-species shape at a different pose/zoom can score worse than
    a same-shaped WRONG species; (c) whole-image grayscale correlation
    has no concept of the game's own strongest free discriminating
    signal - the two type-badge icons next to each sprite, which
    icon_template_matcher.py-style exact-icon matching (not fuzzy
    whole-sprite correlation) could read far more reliably and use to
    narrow candidates before ever touching the sprite pixels at all. That
    cross-reference is NOT built here - it's the most promising next step
    if this capability is revisited.
  - CONFIDENCE GATE mechanism (margin + absolute floor) is kept as
    reasonable-looking infrastructure for a future, more discriminative
    scoring function, but - to repeat - it is NOT validated to reliably
    separate correct from incorrect on the one real sample tested here.
    Treat MIN_SCORE_MARGIN/MIN_ABSOLUTE_SCORE below as placeholders, not
    tuned thresholds.
  - Shiny templates exist in the manifest but are EXCLUDED by default
    (`include_shiny=False`) for the same reason as before (doubling
    candidates adds cost without a demonstrated accuracy benefit) -
    unchanged by any of the above.
  - Performance: whole-manifest whole-sprite comparison at full crop
    resolution measured over 45 SECONDS for one real 6-row column early
    on; downscaling both the crop and every composited reference to a
    small fixed MATCH_SIZE (96x96) before comparing brought that under 2
    seconds for the same real column - this speed fix is real and
    unaffected by the accuracy findings above (it makes the (currently
    unreliable) matching fast, not correct).
  - NOT wired into analyze_matches.py's read_roster() - see above.
"""

import json
import os

import cv2
import numpy as np

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates", "species")
MANIFEST_PATH = os.path.join(TEMPLATES_DIR, "manifest.json")

# Measured 2026-07-06 from jobs/8c10092ac4a9/vod.mp4 (match 1, ~70s) against
# analyze_matches.crop_opponent_sprite_column()'s OWN real output (box
# (0.655, 0.02, 0.76, 0.86), see that function's docstring for why this
# specific box exists) - a row-brightness divider scan found dividers a
# very consistent ~150px apart in the frame's own un-zoomed pixel space,
# converted here to a fraction of a crop taken with top=0.02/bottom=0.86
# (crop height 1083.6px in that specific frame's native 1290px height).
ROW_TOP_FRAC = 147.5 / 1083.6     # top of row 0, as a fraction of crop height
ROW_HEIGHT_FRAC = 149.7 / 1083.6  # each row's height, as a fraction of crop height
MAX_ROWS = 6                      # a team preview shows at most 6 Pokemon

MIN_ROW_HEIGHT_PX = 30           # sanity floor - a row this short is measurement noise, not real content
EMPTY_ROW_MEAN_THRESHOLD = 8.0   # mean pixel value below this = mostly black = no real content (row cut off/absent)

# Background segmentation for _tight_crop_to_sprite - same hue family as
# analyze_matches._ROSTER_PANEL_HUE_RANGE (the team-preview panel's
# magenta/maroon), plus a brightness floor to also catch the near-black
# area OUTSIDE the rounded card corners (that area isn't in the panel hue
# range at all, so the hue check alone misses it).
_BG_HUE_RANGE = (300, 350)   # degrees
_BG_MIN_SAT = 0.20
_BG_MAX_VAL_FOR_DARK = 0.12   # below this brightness = treated as background regardless of hue
_BG_MORPH_KERNEL = 5
_BG_MIN_COMPONENT_SIDE_PX = 10   # a found "sprite" component smaller than this is noise, not real

# HONEST CAVEAT (see module docstring): re-tested against the real,
# corrected crop and did NOT reliably separate the one real correct match
# from real wrong ones - kept as infrastructure for a future, more
# discriminative scoring function, not as a tuned, trustworthy threshold.
MIN_SCORE_MARGIN = 0.03
MIN_ABSOLUTE_SCORE = 0.35

# See module docstring's "Performance" section - this is a real, measured
# speed fix (45s+ -> under 2s for one real 6-row column); it does not
# change (and did not cause) the accuracy findings documented above.
MATCH_SIZE = (96, 96)

_TEMPLATE_CACHE = {}   # filename -> RGBA numpy array, loaded once per process
_MANIFEST_CACHE = None


def load_manifest(manifest_path=MANIFEST_PATH):
    """Loads templates/species/manifest.json (written by
    fetch_species_sprites.py) - cached after the first call. Returns an
    empty list (not an error) if the manifest doesn't exist yet, since a
    user who hasn't run that script yet is an expected, normal state, not
    a crash condition."""
    global _MANIFEST_CACHE
    if _MANIFEST_CACHE is not None:
        return _MANIFEST_CACHE
    if not os.path.exists(manifest_path):
        _MANIFEST_CACHE = []
        return _MANIFEST_CACHE
    with open(manifest_path, encoding="utf-8") as f:
        _MANIFEST_CACHE = json.load(f)
    return _MANIFEST_CACHE


def filter_manifest_by_species(manifest, species_names):
    """Restricts `manifest` entries to just the given species names
    (case-insensitive) - the closed-set filtering this module is meant to
    be used with in practice (the current regulation's legal roster), both
    for accuracy (a real match can only show a legal species) and for
    runtime (comparing against ~100-200 candidates instead of ~360-720)."""
    species_set = {str(s).lower() for s in species_names if s}
    return [e for e in manifest if e.get("species") and e["species"].lower() in species_set]


def _load_reference_rgba(filename, templates_dir=TEMPLATES_DIR):
    """Loads one reference PNG (with alpha channel) - cached after the
    first call, since the same ~360-720 files get compared against
    repeatedly across many sprite crops in one run."""
    if filename in _TEMPLATE_CACHE:
        return _TEMPLATE_CACHE[filename]
    path = os.path.join(templates_dir, filename)
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    _TEMPLATE_CACHE[filename] = img   # cache the miss too (None) - don't re-stat a missing file every time
    return img


def _composite_on_background(rgba, bg_bgr, size):
    """Alpha-composites an RGBA reference image onto a solid `bg_bgr`
    color, resized to `size` (width, height) - see module docstring for
    why this matters (comparing a transparent-background reference against
    an opaque real screenshot crop without this step scored much worse in
    early manual testing). Falls back to a plain resize (dropping any
    alpha) if the source image has no alpha channel at all."""
    resized = cv2.resize(rgba, size, interpolation=cv2.INTER_AREA)
    if resized.ndim == 3 and resized.shape[2] == 4:
        alpha = resized[:, :, 3:4].astype(np.float64) / 255.0
        bgr = resized[:, :, :3].astype(np.float64)
        bg_layer = np.full_like(bgr, bg_bgr, dtype=np.float64)
        out = bgr * alpha + bg_layer * (1 - alpha)
        return out.astype(np.uint8)
    return cv2.resize(rgba[:, :, :3] if resized.ndim == 3 else resized, size)


def _tight_crop_to_sprite(row_bgr):
    """Crops one row band (from slice_sprite_crops) down to just the
    sprite's own silhouette, using a hue/brightness background mask (see
    _BG_HUE_RANGE etc.) plus the LARGEST connected foreground component's
    bounding box - not just the bounding box of every non-background
    pixel, which is fragile against stray noise/anti-aliasing pixels near
    the crop's own edges (tested and found unreliable - see module
    docstring). Falls back to returning `row_bgr` unchanged if no
    component clears `_BG_MIN_COMPONENT_SIDE_PX` in both dimensions (a
    real fallback, not a silent no-op: an all-background or
    all-foreground row shouldn't be force-cropped to something smaller and
    possibly wrong)."""
    hsv = cv2.cvtColor(row_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    h_deg = h.astype(np.float32) * 2   # OpenCV hue is 0-179 -> real degrees
    s_frac = s.astype(np.float32) / 255
    v_frac = v.astype(np.float32) / 255
    hue_lo, hue_hi = _BG_HUE_RANGE
    is_bg_hue = (h_deg >= hue_lo) & (h_deg <= hue_hi) & (s_frac >= _BG_MIN_SAT)
    is_dark = v_frac < _BG_MAX_VAL_FOR_DARK
    bg_mask = is_bg_hue | is_dark
    fg_mask = (~bg_mask).astype(np.uint8) * 255

    kernel = np.ones((_BG_MORPH_KERNEL, _BG_MORPH_KERNEL), np.uint8)
    fg_clean = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
    fg_clean = cv2.morphologyEx(fg_clean, cv2.MORPH_CLOSE, kernel)

    n_components, _labels, stats, _centroids = cv2.connectedComponentsWithStats(fg_clean, connectivity=8)
    if n_components <= 1:
        return row_bgr
    areas = stats[1:, cv2.CC_STAT_AREA]
    best_idx = 1 + int(np.argmax(areas))
    x, y, w, h_box, _area = stats[best_idx]
    if w < _BG_MIN_COMPONENT_SIDE_PX or h_box < _BG_MIN_COMPONENT_SIDE_PX:
        return row_bgr
    return row_bgr[y:y + h_box, x:x + w]


def slice_sprite_crops(column_crop_bgr, max_rows=MAX_ROWS):
    """Divides ONE crop_opponent_sprite_column()-style image into up to
    `max_rows` per-Pokemon sprite sub-images (BGR), top to bottom, each
    then tightened via _tight_crop_to_sprite. A row that falls entirely
    off the bottom of the crop (the source frame didn't show that many
    team-preview slots, or the crop was for a smaller-than-6 format) or
    looks empty/background-only is returned as None in that row's slot -
    callers should treat None as "no data for this slot," never as "this
    slot is empty in-game" (team preview always shows exactly team_size
    Pokemon; a None here is a measurement gap, not a real team-size
    fact)."""
    if column_crop_bgr is None or column_crop_bgr.size == 0:
        return [None] * max_rows
    h, w = column_crop_bgr.shape[:2]
    row_top = ROW_TOP_FRAC * h
    row_height = ROW_HEIGHT_FRAC * h
    out = []
    for i in range(max_rows):
        y0 = int(row_top + i * row_height)
        y1 = int(row_top + (i + 1) * row_height)
        if y0 >= h or (min(y1, h) - y0) < MIN_ROW_HEIGHT_PX:
            out.append(None)
            continue
        y1 = min(y1, h)
        row_img = column_crop_bgr[y0:y1, :]
        if row_img.size == 0 or float(row_img.mean()) < EMPTY_ROW_MEAN_THRESHOLD:
            out.append(None)
            continue
        out.append(_tight_crop_to_sprite(row_img))
    return out


def identify_species_icon(sprite_bgr, candidate_entries=None, include_shiny=False, top_k=3):
    """Compares one sprite crop (as sliced by slice_sprite_crops) against
    every entry in `candidate_entries` (defaults to the full manifest -
    pass a filtered list via filter_manifest_by_species for normal, closed-
    set usage) and returns the top `top_k` matches as
    (score, species, form, shiny) tuples, sorted best-first. `form` is
    None for a template's default/base form. Returns [] if `sprite_bgr` is
    empty/None (nothing to compare) or the manifest/candidate list is
    empty (e.g. fetch_species_sprites.py hasn't been run yet). See module
    docstring's HONEST CURRENT SCOPE - real validation found this only
    correctly identifies about 1 in 6 real rows."""
    if sprite_bgr is None or sprite_bgr.size == 0:
        return []
    entries = candidate_entries if candidate_entries is not None else load_manifest()
    if not include_shiny:
        entries = [e for e in entries if not e.get("shiny")]
    if not entries:
        return []
    # Sample the background color from the FULL-RESOLUTION crop's corner,
    # before downscaling - a corner pixel is a single-pixel sample, and
    # sampling it post-downscale (after any anti-aliasing blur) risks
    # picking up a blend with a neighboring pixel instead of pure background.
    bg = sprite_bgr[min(3, sprite_bgr.shape[0] - 1), min(3, sprite_bgr.shape[1] - 1)].tolist()
    target_size = MATCH_SIZE
    sprite_small = cv2.resize(sprite_bgr, target_size, interpolation=cv2.INTER_AREA)
    sprite_gray = cv2.cvtColor(sprite_small, cv2.COLOR_BGR2GRAY)

    scores = []
    for entry in entries:
        rgba = _load_reference_rgba(entry["filename"])
        if rgba is None:
            continue
        comp = _composite_on_background(rgba, bg, target_size)
        comp_gray = cv2.cvtColor(comp, cv2.COLOR_BGR2GRAY)
        result = cv2.matchTemplate(sprite_gray, comp_gray, cv2.TM_CCOEFF_NORMED)
        score = float(result[0][0])
        scores.append((score, entry["species"], entry.get("form"), bool(entry.get("shiny"))))
    scores.sort(key=lambda t: t[0], reverse=True)
    return scores[:top_k]


def identify_opponent_team_from_column(column_crop_bgr, candidate_species=None,
                                       min_score_margin=MIN_SCORE_MARGIN,
                                       min_absolute_score=MIN_ABSOLUTE_SCORE,
                                       max_rows=MAX_ROWS):
    """High-level, one-crop convenience: slices the column into per-row
    sprites (slice_sprite_crops) and identifies each one
    (identify_species_icon), applying the margin-based confidence gate
    described in the module docstring - NOTE (see HONEST CURRENT SCOPE):
    this gate does NOT reliably separate correct from incorrect matches on
    the real data tested so far; do not treat a row appearing in this
    function's output as a trustworthy identification without further
    validation. Returns a list of dicts: {"row": int, "species": str,
    "form": str or None, "shiny": bool, "confidence": float,
    "runner_up_margin": float}."""
    manifest = load_manifest()
    if candidate_species:
        entries = filter_manifest_by_species(manifest, candidate_species)
        if not entries:   # bad/empty filter - fall back rather than silently matching nothing
            entries = manifest
    else:
        entries = manifest

    sprites = slice_sprite_crops(column_crop_bgr, max_rows=max_rows)
    results = []
    for i, sprite in enumerate(sprites):
        if sprite is None:
            continue
        ranked = identify_species_icon(sprite, candidate_entries=entries, top_k=2)
        if not ranked:
            continue
        top = ranked[0]
        margin = top[0] - ranked[1][0] if len(ranked) > 1 else top[0]
        if top[0] < min_absolute_score or margin < min_score_margin:
            continue
        results.append({
            "row": i, "species": top[1], "form": top[2], "shiny": top[3],
            "confidence": round(top[0], 3), "runner_up_margin": round(margin, 3),
        })
    return results


def merge_column_identifications(crop_results_list):
    """Combines identify_opponent_team_from_column() results from MULTIPLE
    crops of the SAME match (e.g. one per candidate frame
    crop_opponent_sprite_column() returned) into one result. A team-preview
    row's order is fixed for a given match, not frame-dependent, so the
    same row index names the same Pokemon in every crop - this keeps
    whichever crop scored each row index highest, rather than trusting
    only the first crop that happened to include that row at all. Returns
    the same per-row dict shape, deduplicated and sorted by row index."""
    best_by_row = {}
    for results in crop_results_list:
        for r in results:
            row = r["row"]
            if row not in best_by_row or r["confidence"] > best_by_row[row]["confidence"]:
                best_by_row[row] = r
    return [best_by_row[k] for k in sorted(best_by_row)]
