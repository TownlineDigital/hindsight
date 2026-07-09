"""
Extracts and reads the on-screen text elements of a Pokemon VGC battle
frame - the bottom narration banner ("X used Y!", "It's super effective!",
etc.) and a side's name/HP plate - using local OCR (tesseract via
pytesseract) instead of a Gemini vision call. Feed the banner's text to
battle_text_parser.parse_line()/parse_lines() to get a structured event;
see ARCHITECTURE_HANDOFF.md for the full reasoning and validation behind
building this at all.

Preprocessing recipe (arrived at by testing against REAL captured frames
from this project's own test run, not guessed - see each function's
docstring for what's validated and what isn't):

  1. Crop the specific screen region a UI element lives in.
  2. Upscale. The source frames sampled elsewhere in this pipeline are
     640px wide to keep Gemini vision calls cheap - nowhere near enough
     resolution for small on-screen text. OCR needs a bigger, sharper
     version of just the region that matters, which is why this module
     expects to be handed higher-resolution frames than analyze_matches.py
     normally samples (see the "native vs. downscaled" note in
     ARCHITECTURE_HANDOFF.md).
  3. Isolate near-white, low-saturation pixels in HSV space. The game's
     text is consistently white/near-white regardless of what's behind it
     (a busy checkered floor, a colored name-plate gradient, flame
     effects) - this isolates it far more reliably than a single fixed
     grayscale brightness cutoff, which read one real frame perfectly and
     came back garbled on another during testing.
  4. INVERT to black-text-on-white. This was the single biggest lever
     found during testing: tesseract's bundled models assume dark text on
     a light background, and a technically-clean white-on-black mask
     produced garbage output until this step was added - going from
     unreadable to a perfect, exact match on the same image.
  5. Pad with a white border - tesseract handles text with margin around
     it noticeably better than text touching the image edge.

Known limitation, stated honestly: this recipe is validated well against
the bottom narration banner (two real frames, two exact reads). The
name/HP plate reader is rougher (stylized italic font over a colored/
textured gradient background, not plain text over a mostly flat one) -
it reads reasonably (name, HP as two numbers) but noisier, and only ONE
plate position has actually been tested against real footage so far, not
all four a doubles battle can show at once. Ability/item callouts that
float next to a Pokemon's sprite (rather than appearing in the bottom
banner) aren't targeted by either function here at all yet. Treat a
missing/garbled OCR result as a real signal to fall back to a Gemini
vision read for that moment, not something to force a guess out of.
"""

import re

import cv2
import numpy as np
import pytesseract

# Fractional (top, bottom, left, right) crop of the FULL frame - tuned and
# verified against real 1920x1080 VGC broadcast footage captured during
# this project's own testing (see ARCHITECTURE_HANDOFF.md's OCR write-up).
# If a different broadcast layout or resolution is ever used, these need
# re-validating against real frames the same way, not assumed to transfer.
BOTTOM_BANNER_REGION = (0.72, 0.85, 0.0, 1.0)

# The ONE name/HP plate position actually validated against real footage
# so far (a plate in the bottom-left area). A doubles battle can show up
# to four of these at once (two per side) - the other three positions
# have NOT been confirmed against real frames yet and should be measured
# from real footage before being trusted, not guessed by symmetry.
NAME_PLATE_VALIDATED = (0.83, 0.98, 0.0, 0.24)

# Four broad, overlapping regions used ONLY by species_readable_in_frame()'s
# presence check below - deliberately NOT the one precise NAME_PLATE_VALIDATED
# box. Pokemon Champions' broadcast camera moves dynamically across the 3D
# field rather than holding a fixed overlay position (unlike the footage
# BOTTOM_BANNER_REGION/NAME_PLATE_VALIDATED were tuned against - see module
# docstring), so a name plate can land almost anywhere on screen depending on
# framing/zoom, and a single fixed crop simply won't reliably contain it.
# These trade precision for coverage: the goal here isn't reading an exact HP
# number from one known spot, just "is this Pokemon's name legible ANYWHERE
# in this frame at all" - a much lower, more tolerant bar than the other
# functions in this module attempt.
# NOT yet validated against real Pokemon Champions footage (none is bundled
# in this repo) - a documented first-pass heuristic, not a proven read. Same
# honesty standard accuracy_addons/hp_bar_reader.py holds its own regions to.
VISIBILITY_SCAN_BANDS = (
    (0.0, 0.35, 0.0, 1.0),   # top strip
    (0.65, 1.0, 0.0, 1.0),   # bottom strip
    (0.0, 1.0, 0.0, 0.3),    # left column
    (0.0, 1.0, 0.7, 1.0),    # right column
)


def _crop(frame, region):
    h, w = frame.shape[:2]
    top, bottom, left, right = region
    return frame[int(h * top):int(h * bottom), int(w * left):int(w * right)]


def _isolate_text(crop_bgr, upscale=4, sat_max=60, val_min=190):
    """The validated preprocessing recipe (see module docstring): upscale,
    isolate near-white/low-saturation pixels in HSV, invert to black-on-
    white, pad with a white border. Returns a single-channel image ready
    for pytesseract. Returns None if the crop is empty (a region outside
    the actual frame bounds) rather than letting cv2 raise deep inside."""
    if crop_bgr is None or crop_bgr.size == 0:
        return None
    big = cv2.resize(crop_bgr, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    hsv = cv2.cvtColor(big, cv2.COLOR_BGR2HSV)
    lower = np.array([0, 0, val_min])
    upper = np.array([180, sat_max, 255])
    mask = cv2.inRange(hsv, lower, upper)
    inverted = cv2.bitwise_not(mask)
    padded = cv2.copyMakeBorder(inverted, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    return padded


def _clean_text(raw):
    """Common OCR artifacts: stray punctuation-only tokens from UI icons
    (gender symbols, decorative marks), repeated whitespace. Deliberately
    conservative - only strips characters that are never part of real
    battle text, never touches letters/digits/apostrophes/basic punctuation
    a real line of battle text could legitimately contain."""
    text = re.sub(r"[^\w\s'!.,%/-]", " ", raw or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def read_bottom_banner(frame, psm=6):
    """Reads the bottom narration banner from one video frame (a BGR numpy
    array, e.g. from cv2.imread) - the scrolling text that narrates every
    action. Returns the cleaned text, or "" if nothing legible was found
    (the caller should treat that as "no OCR-derived event here", not an
    error) - ready to hand to
    battle_text_parser.parse_line()/parse_lines()."""
    processed = _isolate_text(_crop(frame, BOTTOM_BANNER_REGION))
    if processed is None:
        return ""
    raw = pytesseract.image_to_string(processed, config=f"--psm {psm}")
    return _clean_text(raw)


def read_name_hp_plate(frame, region=NAME_PLATE_VALIDATED, upscale=3):
    """Reads one side's name/HP plate. `region` defaults to the one
    position actually validated against real footage
    (NAME_PLATE_VALIDATED) - pass an explicit region for any other plate
    position, but see the module docstring's caveat before trusting it as
    much as the default.

    Returns (display_name, hp_current, hp_max, hp_percent) - any of the HP
    fields may be None if that particular number wasn't legible (a
    percent-only plate has no hp_max; a fully garbled read has neither).
    `display_name` is whatever text is actually shown - a nickname or the
    species name, there's no way to tell which from text alone (see
    pokemon_identity.py, which resolves that ambiguity separately)."""
    processed = _isolate_text(_crop(frame, region), upscale=upscale)
    if processed is None:
        return None, None, None, None
    raw = pytesseract.image_to_string(processed, config="--psm 6")
    text = _clean_text(raw)

    hp_current = hp_max = hp_percent = None
    pct_match = re.search(r"(\d{1,3})\s*%", text)
    if pct_match:
        hp_percent = int(pct_match.group(1))
    frac_match = re.search(r"(\d{1,3})\s*/\s*(\d{1,3})", text)
    if not frac_match:
        # OCR sometimes drops the "/" between two adjacent HP numbers (seen
        # during real testing - "155/155" came back as "155 155") - two
        # 1-3 digit numbers with nothing else between them is still a
        # strong enough signal to treat as current/max HP.
        frac_match = re.search(r"\b(\d{1,3})\s+(\d{1,3})\b", text)
    if frac_match:
        hp_current, hp_max = int(frac_match.group(1)), int(frac_match.group(2))
        if hp_max:
            hp_percent = hp_percent or round(100 * hp_current / hp_max)

    # Whatever's left after stripping digits/%//junk is the display-name
    # candidate - takes the longest alphabetic run, since short leftover
    # fragments (a stray gender-symbol artifact, single stray letters) are
    # usually OCR noise rather than part of the real name.
    words = [w for w in re.split(r"[\s/%]+", text) if w.isalpha() and len(w) > 1]
    display_name = max(words, key=len) if words else None

    return display_name, hp_current, hp_max, hp_percent


def _norm_word(w):
    """Lowercase, letters/digits only - same normalization convention as
    analyze_matches._norm()/pokemon_identity._norm(), kept as its own local
    copy rather than importing a private helper across module boundaries."""
    return re.sub(r"[^a-z0-9]", "", str(w or "").lower())


def _text_matches_any(text, targets_normalized):
    """True if any word in `text` plausibly matches one of the already-
    normalized `targets_normalized` - a startswith/prefix check (same
    tolerance pokemon_identity._fuzzy_match uses for a real roster name),
    not exact-only, since OCR often drops or garbles a trailing letter.
    Deliberately requires len >= 4 on both sides to avoid a short common
    fragment ("on", "the") coincidentally "matching" a real name. Split out
    from species_readable_in_frame() so this matching logic can be unit
    tested against a plain string, without needing pytesseract/cv2 to
    actually run against a real image."""
    for w in re.split(r"\s+", text or ""):
        nw = _norm_word(w)
        if len(nw) < 4:
            continue
        for t in targets_normalized:
            if len(t) >= 4 and (nw.startswith(t) or t.startswith(nw) or nw == t):
                return True
    return False


def species_readable_in_frame(frame, candidate_names, bands=VISIBILITY_SCAN_BANDS):
    """Best-effort, LAYOUT-TOLERANT check for whether any of `candidate_names`
    (e.g. a guessed species plus any known aliases/nickname) is legible as
    on-screen text ANYWHERE in this frame - see VISIBILITY_SCAN_BANDS for why
    this scans several broad regions instead of trusting one fixed plate
    position. Built specifically for analyze_matches.py's
    cross_check_reference_frame_visibility(): a photo attached to an event
    as its "reference_frame" is picked by nearest TIMESTAMP, with no
    guarantee the camera was actually pointed at the relevant side at that
    instant (Pokemon Champions' camera pans across the field) - this is the
    honest, after-the-fact check for whether that assumption actually held
    for one specific photo.

    Returns True if a legible match was found in any scanned region, False if
    none were. A False result is a MUCH stronger signal than a True one: OCR
    can easily miss text that's genuinely on screen (small, angled, motion-
    blurred, partially obscured), so callers should treat True as "plausibly
    visible, not proof" but False as close to "very likely not on screen at
    all in this photo" - phrase anything built on this accordingly (see
    ClarificationQueue.jsx's isTeamPreviewFallback-style honest labeling),
    never as absolute certainty either way.

    NOT yet validated against real Pokemon Champions captures (see
    VISIBILITY_SCAN_BANDS) - a documented first pass, not a proven read."""
    targets = {_norm_word(n) for n in (candidate_names or []) if n}
    targets.discard("")
    if not targets:
        return False
    for region in bands:
        processed = _isolate_text(_crop(frame, region), upscale=3)
        if processed is None:
            continue
        raw = pytesseract.image_to_string(processed, config="--psm 6")
        text = _clean_text(raw)
        if _text_matches_any(text, targets):
            return True
    return False
