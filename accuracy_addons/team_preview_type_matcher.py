"""
Free, local (no API call) TYPE-BADGE identification for the opponent's
team-preview roster column - the more promising follow-up to
accuracy_addons/species_icon_matcher.py's whole-sprite pixel correlation
(that module's own HONEST CURRENT SCOPE docstring found only ~1/6 real rows
correct and explicitly named "cross-referencing the type badges" as the most
promising untried next step - this module IS that next step).

WHY BADGES INSTEAD OF SPRITES: each team-preview row shows the sprite AND
1-2 small type-badge icons (Fire/Water/Dark/Steel/etc. - the same icons the
in-battle move-info panel uses, just at a different scale/crop) next to it.
A type badge is a small, flat-colored, high-contrast icon with almost no
pose/lighting/background variance between instances - a much easier target
for pixel-correlation matching than a full sprite silhouette. Real
validation (2026-07-06, job 8c10092ac4a9 match 1, ~70s) confirmed this
directly: cross-instance same-type badges scored 0.928-0.949 against each
other, while different-type badges scored at most ~0.4-0.8 (a real margin of
0.3-0.5) - dramatically better separation than species_icon_matcher's
~0.03-0.05 margins on the same footage.

HOW IT WORKS:
  1. `slice_badge_rows()` divides ONE analyze_matches.crop_opponent_badge_
     column()-style image into up to 6 per-Pokemon row bands, using the
     SAME row-divider constants as species_icon_matcher.py (both
     crop_opponent_sprite_column and crop_opponent_badge_column use the same
     top=0.02/bottom=0.86 vertical extent, measured from the same real
     frame, so the row math transfers directly).
  2. `find_badge_components()` isolates the 1-2 actual badge icons within a
     row band's TOP portion (badges sit above the gender icon), via the same
     hue/brightness background mask species_icon_matcher.py uses (same
     magenta/maroon panel), then filters connected components by minimum
     size AND aspect ratio (badges are roughly square; a stray thin
     card-edge/divider artifact found in real testing was NOT square and is
     excluded this way), sorted left to right.
  3. `identify_badge_type()` compares one isolated badge crop against every
     reference template for every known type (see TEMPLATES_DIR) and returns
     the best type match, IF it clears MIN_BADGE_MATCH_SCORE - unlike
     species_icon_matcher's margin gate (found NOT to reliably separate
     right from wrong), this threshold IS grounded in a real, large measured
     gap (see numbers above) between same-type and different-type scores.
  4. `identify_row_types()` ties 2+3 together for one row band, returning
     both which types were confidently identified AND how many badge-shaped
     components were physically found - that second number matters for
     narrow_species_by_types (see its own docstring for why: a row with only
     ONE physical badge component is a genuinely mono-type Pokemon, which is
     a much stronger narrowing signal than "we only managed to classify one
     of two present badges"). Since 2026-07-06, this step also applies
     `_refine_oversized_badge_crop()` when the second badge's detected box is
     anomalously large relative to the first (a real, diagnosed connected-
     component merge failure - see HONEST CURRENT SCOPE) - see that
     function's own docstring for how the recovery search works.
  5. `identify_row_types_multi_frame()` combines identify_row_types() across
     several real crops of the SAME row from different frames of one match's
     team-preview screen, via majority vote - the real fix for the frame-
     sensitivity finding described below.
  6. `narrow_species_by_types()` filters a candidate species list (normally
     the current regulation's own legal roster - see
     accuracy_addons/data/species_types.json) down to species whose real
     type combination is consistent with what was identified for one row.

HONEST CURRENT SCOPE (real, checked - not assumed):
  - REAL END-TO-END RESULT, re-tested across 7 real frames (2026-07-06, job
    8c10092ac4a9 match 1, the SAME 6 real rows species_icon_matcher.py only
    got 1/6 correct on): after fixing a real template-mislabeling bug (see
    below), the module was run against 7 different real frames of this same
    static team-preview screen, sampled ~1s apart (t=68,69,70,70.5,71,72,73s)
    at the SAME 1024px-wide scale the production pipeline actually samples
    at. Two real findings came out of this broader retest, and both matter:
      1. THE SAFETY PROPERTY HOLDS PERFECTLY: across all 7 frames x 6 rows
         (42 checks), the true species was in narrow_species_by_types'
         candidate list every single time - 42/42, never wrongly excluded.
         This is the property that actually matters for safe use (a caller
         combining this with other signals is never steered away from the
         truth), and it held up under this harder, multi-frame test.
      2. FULL both-badge identification (both real types correctly named,
         narrowing to the tightest possible candidate list) is genuinely
         frame-sensitive, even within the SAME static screen: the number of
         rows getting a full, both-type-correct read ranged from 3/6 to 5/6
         across the 7 frames tested (BEFORE the crop-refinement fix below).
      3. A SEPARATE, PREVIOUSLY UNDISCOVERED FAILURE MODE: badge-COUNT
         detection itself (find_badge_components) is occasionally noisy
         even for a genuinely mono-type Pokemon. Blastoise (real mono-
         Water) showed num_badges_found=2 instead of 1 in 2 of the 7 frames
         (t=72s, 73s) - likely a spurious second component from
         compression/motion noise near the gender icon boundary. This
         matters because narrow_species_by_types' rule depends on
         num_badges_found: a wrongly-detected second badge silently
         downgrades the match from the strong "exact single-type" rule to
         the weaker "contains this one type" rule (27 candidates instead of
         10) - the real species was still included both times, but the
         narrowing was needlessly looser.
  - ROOT CAUSE FOUND AND FIXED for Kingambit's (dark/steel) persistent
    steel-badge miss (2026-07-06, follow-up investigation): it was NOT a
    template-quality problem. The background-segmentation connected-
    component step was occasionally MERGING the real steel badge with
    whatever sits directly above/around it in the panel (a real, measured
    artifact - e.g. one malformed box was 58x67px instead of the real
    ~37x36px), producing a badly distorted crop that no longer resembled a
    badge once squashed to the 64x64 comparison size - so it scored low
    against EVERY type (0.45-0.65), not specifically against steel. This
    was confirmed by (a) measuring that every OTHER row's real, correctly-
    identified second badge sits at a highly consistent position/size
    (median offset from the first badge: dx~47px, dy~2px, ~37x36px, across
    24 confirmed-clean real badge pairs), and (b) an exhaustive local
    position/size search within the malformed box's own footprint reliably
    recovering a clean, correctly-scoring steel crop (0.94-0.97) at
    (approximately) that expected relative position.
    FIX: `_refine_oversized_badge_crop()` - when the second badge's box is
    anomalously large relative to the first (BADGE_SIZE_ANOMALY_RATIO),
    slide a small set of real badge-sized windows (REFINE_SIZE_OPTIONS)
    across a generous margin (REFINE_SEARCH_MARGIN_PX) around the malformed
    box and keep whichever sub-crop scores best against any template - this
    directly recovers the real badge pixels submerged inside the malformed
    region, rather than trusting the merged box's own reported geometry.
    REAL RE-VALIDATION after this fix, same 7 frames: Kingambit's dark+steel
    pair was fully, correctly identified in 6 of 7 frames (up from 1 of 7)
    - full 6/6-row exact identification was reached on 2 of the 7 individual
    frames (t=68, t=70.5), and the aggregate across all 7 frames/6 rows went
    from 29/42 to 34/42 correct-both-type reads, with ZERO new safety
    violations (the true species stayed in the candidate list in all 42
    checks, exactly as before). One case remains genuinely unfixed: t=72s,
    where a SEPARATE, more severe artifact (a component spanning nearly the
    ENTIRE row's width, seen at both Kingambit's and Blastoise's rows at
    that exact timestamp - almost certainly a shared visual glitch, e.g. a
    transition/compression flash, not specific to either Pokemon) occupies
    one of only MAX_BADGES_PER_ROW=2 badge "slots," which can crowd out the
    real second badge entirely rather than merely distorting it - this is a
    qualitatively different, harder failure (component starvation, not
    geometry distortion) that the local-search fix does not address, and
    which was deliberately NOT "fixed" by adding an outright size-based
    rejection filter: an earlier attempt at that regressed several OTHER
    rows' safety property (real dual-typed species got wrongly reduced to
    num_badges_found=1 and then wrongly EXCLUDED by the exact-match rule) -
    a serious, caught-before-shipping regression. The final, shipped fix
    intentionally only ever repositions the SECOND badge crop, never
    rejects/removes a detected component, preserving the safety property
    above every other consideration.
  - MULTI-FRAME AGGREGATION (identify_row_types_multi_frame), added as the
    first fix attempted for the frame-sensitivity finding above, and
    RE-TESTED against the SAME 7 real frames as a majority vote (threshold
    4/7) across all of them at once: 5 of 6 rows got a full, exact type
    match (Delphox, Sneasler, Incineroar, Blastoise, Sinistcha) even BEFORE
    the crop-refinement fix above - matching the best any single frame had
    achieved, but deterministically. The Blastoise badge-COUNT noise
    (finding 3 above) was also fully resolved by the vote: majority
    correctly resolved 5-frames-said-1-badge vs. 2-frames-said-2-badges to
    the true single-badge read. Kingambit did NOT reach a full match under
    aggregation alone (its steel badge was classified in only 1 of 7 frames
    pre-refinement, below the 4-frame majority threshold) - this is exactly
    why the crop-refinement fix above was pursued as a second, complementary
    fix: aggregation smooths over frame-to-frame NOISE but cannot recover a
    badge that was never correctly read in enough individual frames to begin
    with; fixing the underlying per-frame read (crop refinement) is a
    different, necessary lever. RE-MEASURED TOGETHER after the crop-
    refinement fix landed: running identify_row_types_multi_frame() over
    the SAME 7 real frames (now with crop refinement active on each
    individual frame first) reached a FULL, EXACT 6/6 - every one of the
    6 real rows, including Kingambit's dark+steel pair narrowing to
    exactly 1 candidate species. This is the current best validated
    result for this module: the two fixes are complementary (crop
    refinement fixes the per-frame read; aggregation smooths over the
    frames refinement still can't fully recover, like t=72s) and their
    combination is what should be used together, not either in isolation.
  - REAL BUG FOUND AND FIXED while validating the above: the first pass at
    building these templates (during exploratory work before this module
    existed) mislabeled two of them - the file saved as "type_fairy.png"
    was actually Delphox's real PSYCHIC badge, and the file saved as
    "type_psychic.png" was actually Sneasler's real POISON badge (Psychic
    and Fairy badges are both pink and easy to visually mix up at this
    crop's resolution; Poison's purple was apparently misjudged as Psychic's
    pink too). Caught by re-deriving the same real frame from scratch and
    finding the "wrong" template scored 0.99+ against the WRONG real badge
    while the "correct" type scored far lower - a real, measured
    contradiction, not a hunch. Fixed by relabeling: the real Psychic badge
    is now correctly named type_psychic.png, and the real Poison badge
    (previously not captured as its own template at all) is now
    type_poison.png - a net gain of one type's real coverage as a side
    effect of the fix. No real Fairy-type badge has been captured from this
    footage yet (none of these 6 rows' Pokemon are Fairy-type), so
    "fairy" is NOT currently a covered type despite once having a
    (wrongly-labeled) file - see the coverage list below.
  - Template coverage is 14 of the real game's 18 types (fire, poison,
    fighting, psychic, dark, steel, water, grass, ghost, fairy, dragon,
    ground, electric, normal) - captured directly from real team-preview
    footage at the correct scale/context (a real, previously-undiscovered
    problem with reusing icon_template_matcher.py's existing move-type
    templates for this UI element: those are 24x24px captures from the
    battle move-info panel, a DIFFERENT screen at an incompatible scale/
    crop, and testing them against real team-preview badges gave
    inconsistent results - e.g. the correct "dark" template scored LOWEST
    among all candidates for a real dark badge, with a wrong "electric"
    template scoring highest). The remaining 4 types (flying, rock, bug,
    ice) have NO validated template here yet - a row whose only
    unidentifiable badge is one of these 4 will correctly report "some
    badge is present here but not classified" rather than silently
    guessing.

    UPDATE (2026-07-07): fairy/dragon/ground added, at the user's own
    request after they asked whether manually labeling more real badge
    crops would help and offered to review candidates directly. Found via
    a real, repeatable procedure worth reusing for the remaining 6: every
    already-extracted badge crop from jobs/8c10092ac4a9 matches 1-2 (111
    real instances, saved incidentally during earlier roster reads - zero
    extra Gemini/ffmpeg cost) was scored against the then-9 templates and
    grouped by (match, row, badge-slot); 3 slots' scores never crossed
    MIN_BADGE_MATCH_SCORE across 6-8 independent frame samples each (one
    never crossed even 0.7) - a real, consistent gap across many samples,
    not one noisy crop. The isolated images were shown to the user, who
    identified all three by eye: match_2 row1's second badge = Fairy,
    match_2 row5's second badge = Dragon, and match_2 row5's first badge
    (originally mis-isolated by the same oversized-crop merge issue
    described above for Kingambit - the real ground icon was recovered by
    re-splitting the merged box) = Ground. After adding these three real
    templates: 0 of the 111 instances remain below threshold, and - a real,
    independent cross-check, not just the self-matching source instances -
    3 previously-unclassified match_1 badge slots (row3 badge0, row3
    badge1, row5 badge0) that were never used to build the Ground template
    now also score 0.89-0.97 against it, confirming Ground genuinely
    generalizes beyond its one source crop rather than only matching
    itself. Fairy and Dragon's own scores (1.000 each) are self-match only
    so far - not yet independently cross-validated the way Ground was,
    since no other captured instance of either type existed in this
    footage.

    UPDATE (2026-07-07, same session): electric/normal added, via the exact
    same procedure extended across jobs/8c10092ac4a9 matches 3, 4, and 5
    (56 total badge-slot instances across matches 1-5 after this batch).
    Two consistently-below-threshold slots (match_5 row0 badge0, n=4
    samples, max 0.773; match_4 row5 badge0, n=3 samples, max 0.674) were
    shown to the user, who identified them as Electric (a yellow badge with
    a white lightning bolt) and Normal (a plain gray circle on white)
    respectively - both clean, unambiguous, roughly-square single-badge
    crops (aspect ratio ~1.0, not a merge artifact this time). After adding
    them: 9 of the 56 total slots remain below threshold (down from 11
    before this batch, since these two are now resolved) - re-verified with
    zero regressions on any of the 47 already-passing slots. Two of the 9
    still-below slots now guess "electric" or "normal" as their best (but
    still sub-threshold) match (match_5 row3 badge1 -> electric 0.502;
    match_5 row4 badge0 -> normal 0.438) - these MAY be additional real
    instances of the same two types with a noisier crop, or may be
    something else entirely; not yet confirmed either way, so treat this as
    an open lead for the next pass, not a finding. The same "extract
    already-sampled crops, find slots that never clear threshold across
    several independent frames, show the user the isolated icon" procedure
    is the recommended path for capturing the remaining 4 types too,
    whenever footage containing them becomes available.

    UPDATE (2026-07-08): a COLOR cross-check added (_average_color,
    identify_badge_type_with_color - see their own docstrings), at the
    user's own suggestion ("is matching by color an option?"). Grounded in
    a real measurement first, not assumed: average-BGR distance was
    computed between every confidently-shape-matched real badge instance
    (score >= MIN_BADGE_MATCH_SCORE, used as trusted ground truth) and
    every template's own average color, across all 56 real instances from
    jobs/8c10092ac4a9 matches 1-5 (130 same-type comparisons, 1690
    different-type comparisons). Real result: same-type distances mean=9.1
    (p90=12.9), different-type distances mean=104.2 (p10=52.6) - a large,
    real separation, BUT with one same-type OUTLIER at distance 147.8 (a
    badly cropped/lit real instance) that lands well inside different-type
    territory. Because of that outlier, color is NOT used to gate/reject a
    shape match here (a hard color cutoff would have wrongly rejected that
    one real correct match) - it is used ONLY as an ADDITIVE confidence
    bonus on top of the existing shape score (see COLOR_DISTANCE_SCALE/
    COLOR_AGREEMENT_FLOOR/COLOR_BONUS_MAX), capped so a badge that already
    clears MIN_BADGE_MATCH_SCORE on shape alone can NEVER be pushed back
    below it by a disagreeing color - re-verified directly against all 56
    real instances: 0 regressions.

    HONEST RESULT ON THE TWO OPEN LEADS ABOVE: the color cross-check did
    NOT confirm either lead as hoped, and the real reason is informative -
    checked directly against every real sampled frame of each slot, color's
    OWN independent best-matching type actively DISAGREED with shape's weak
    guess in every case, so no bonus applied (the additive design only
    boosts a badge's score for the type shape ALREADY guessed; it does not
    grant credit toward a type shape didn't pick). Concretely: match_5 row4
    badge0 ("normal-lead", shape score 0.438) had color distances of just
    20-83 to the GROUND template across all 4 sampled frames - consistently
    the closest color match by a wide margin - while shape's own guess
    wandered between normal/poison/dark/ghost/fairy frame to frame (each
    itself far in color, distance 137-256). This is real, useful signal
    pointing a different direction than originally assumed: this slot is
    more likely a poorly shape-matched instance of Ground (already a
    covered type) than a new, uncovered type - worth a fresh visual look,
    not more template-hunting. match_5 row3 badge1 ("electric-lead", shape
    score 0.502) was murkier: color's own best guess varied between Dragon
    and Fire across frames, neither matching shape's inconsistent
    grass/electric guesses either - this one remains genuinely unresolved.

    Overall re-verification across all 56 real slots with the color
    bonus enabled: 0 of the 9 still-below-threshold slots crossed
    MIN_BADGE_MATCH_SCORE (matching the "no regressions, but no free lunch
    either" honest expectation for a same-type-outlier-aware, bonus-only
    design) - the color signal is real and worth keeping (it is a genuine,
    previously-unused piece of evidence, and the Ground-color finding above
    is a real, actionable lead), but on this specific real dataset it did
    not resolve any previously-ambiguous badge on its own.
  - species_types.json (the species->type-combination data this module's
    narrowing function reads) was built from PokeAPI's real
    /api/v2/type/{name} data for all 18 types, cross-referenced against the
    M-B regulation's real 212-species legal roster - every entry was checked
    against real API data, not filled in from memory.
  - MIN_BADGE_MATCH_SCORE (unlike species_icon_matcher's margin gate) IS
    grounded in a real measured gap on real footage (same-type badges
    scored 0.928-0.996 against each other on the corrected templates;
    different-type badges scored at most ~0.5-0.8) - but this has only been
    validated against ONE real match (7 frames of its single team-preview
    screen) so far. Treat the 42/42 candidate-list-recall result as a real,
    solid finding, and the frame-to-frame both-badge accuracy as a real,
    improving-but-not-fully-solved limitation - not yet tested against a
    different match/lighting/camera-angle.
  - narrow_species_by_types does NOT claim to always narrow to exactly one
    species - for a common type combination (e.g. Water alone matches many
    legal species), it returns every candidate that's consistent with what
    was seen; callers should combine this with other signals (sprite
    silhouette, on-screen name text, etc.), not treat it as a standalone
    identifier.
  - NOT wired into analyze_matches.py's read_roster() yet - promising for
    its candidate-list-recall property (unlike species_icon_matcher.py,
    which was NOT reliable enough to use even as a filter), but still only
    validated against one real match; see ARCHITECTURE_HANDOFF.md for the
    wiring decision and what would need to happen first (more real matches
    with different type combinations, ideally including one of the 4
    not-yet-covered types, sampled at multiple frames per match so
    identify_row_types_multi_frame has real material to vote over).
"""

import json
import os

import cv2
import numpy as np

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates", "team_preview_types")
SPECIES_TYPES_PATH = os.path.join(os.path.dirname(__file__), "data", "species_types.json")

# Same real-measured row geometry as species_icon_matcher.py - both
# crop_opponent_sprite_column and crop_opponent_badge_column in
# analyze_matches.py use the same box top (0.02) / bottom (0.86) fractions
# of the source frame, so a crop's OWN height maps to the same row
# boundaries regardless of which of the two (sprite vs. badge) crop it is.
ROW_TOP_FRAC = 147.5 / 1083.6
ROW_HEIGHT_FRAC = 149.7 / 1083.6
MAX_ROWS = 6
MIN_ROW_HEIGHT_PX = 20
EMPTY_ROW_MEAN_THRESHOLD = 8.0

# A row band shows 2 badges stacked ABOVE a gender icon - restricting the
# badge search to the row's own top fraction excludes that gender icon
# (found, in real testing, to otherwise occasionally get picked up as a
# spurious third "badge" component).
BADGE_SEARCH_TOP_FRACTION = 0.62

# Same background hue/brightness segmentation as
# species_icon_matcher._tight_crop_to_sprite - same real magenta/maroon
# team-preview panel, so the same mask applies here.
_BG_HUE_RANGE = (300, 350)
_BG_MIN_SAT = 0.20
_BG_MAX_VAL_FOR_DARK = 0.12
_BG_MORPH_KERNEL = 3

# A real badge is roughly square - found (real testing) to correctly reject
# a spurious ~167x36px thin horizontal strip (a card-edge/divider artifact)
# in one row while keeping the two real ~50x50 badge components.
MIN_BADGE_SIDE_PX = 15
MAX_BADGE_ASPECT_RATIO = 2.0
MIN_BADGE_ASPECT_RATIO = 0.5
MAX_BADGES_PER_ROW = 2

MATCH_SIZE = (64, 64)   # real captured template size

# Grounded in a real measured gap (see module docstring): same-type badges
# scored 0.928-0.949 against each other; different-type badges scored at
# most ~0.4-0.8 on the one real match tested so far.
MIN_BADGE_MATCH_SCORE = 0.85

# Real, measured color separation (2026-07-08, all 14 covered types, 130
# same-type vs 1690 different-type comparisons across every confidently
# shape-matched real badge instance from jobs/8c10092ac4a9 matches 1-5, used
# as trusted ground truth): same-type average-BGR distance mean=9.1
# (p90=12.9), different-type mean=104.2 (p10=52.6) - separated well on
# average, but with one real same-type OUTLIER at distance 147.8 (a badly
# cropped/lit instance) that overlaps different-type territory. That
# outlier is exactly why color is used ONLY as an additive bonus below, not
# a hard gate - see identify_badge_type_with_color's own docstring.
COLOR_DISTANCE_SCALE = 150.0   # dist=0 -> similarity 1.0; dist>=150 -> 0.0
COLOR_AGREEMENT_FLOOR = 0.70   # below this color-similarity, zero bonus -
                               # real different-type median distance 100.8
                               # maps to similarity ~0.33, safely under this
COLOR_BONUS_MAX = 0.15   # capped: the real gap between MIN_BADGE_MATCH_SCORE
                         # (0.85) and a perfect 1.0 shape score

# Real measured evidence (2026-07-08, job 8c10092ac4a9 matches 4-5, a live
# production rerun): identify_row_types_multi_frame's DEFAULT majority
# threshold ((n // 2) + 1) works well for one homogeneous batch of frames
# (validated at n=7 - see TestRealFootageMultiFrameAggregation), but
# read_roster() pools frames from ALL 5 ROSTER_SEARCH_ATTEMPTS together
# (see analyze_matches.attach_opponent_type_hints) - most of a single
# search attempt's own sampled frames are NOT on the fully-settled
# team-preview screen at all (still mid-transition), so a real per-badge
# confirmation lands in only a handful of the total pooled frames even
# when it scores a clean 1.0 on the frames that DO show the settled
# screen. A plain majority of a large, mostly-irrelevant pool (e.g. 10 of
# 18) is never reached by a true signal that only appears ~3 times - this
# is exactly what caused two real matches to come back with ZERO
# confident type reads despite every real badge scoring 1.0 on the one
# settled frame per attempt. CAPPING the required agreement at a small
# absolute number fixes this without loosening things enough to let noise
# through: real-measured on an 18-frame pool (job 8c10092ac4a9 match 4,
# all 5 attempts pooled, real opponent Gengar/Incineroar/Sinistcha/
# Corviknight/Garchomp/Staraptor), requiring only 2 confirmations let a
# genuine FALSE POSITIVE through (Corviknight's row: its real second type,
# Flying, isn't covered by any template, but "dragon" scored high enough
# by coincidence to hit 2/18 - confirming it alongside the real "steel"
# would produce a type PAIR that doesn't match any real species and would
# have wrongly EXCLUDED Corviknight from narrow_species_by_types' exact-
# pair match). Requiring 3 confirmations excluded that false positive
# while still correctly confirming every genuinely-present covered type
# that appeared at least 3 times across the same real pool (Gengar's
# Ghost, Incineroar's Fire+Dark, Sinistcha's Grass+Ghost, Garchomp's
# Dragon, Staraptor's Normal all confirmed correctly). The one real cost:
# Gengar's second type (Poison) only reached 2/18 real confirmations and
# is missed at this cap - an honest, measured trade-off, not a free win;
# a lower cap would restore it but at the cost of the Corviknight false
# positive above, which this module's own "never wrongly exclude the true
# species" safety property treats as the more dangerous failure mode.
MAX_FRAME_AGREEMENT_CAP = 3

# If the second badge's box is more than this much larger (width OR height)
# than the first badge's box, treat it as a real connected-component merge
# artifact (see module docstring's ROOT CAUSE section) rather than trusting
# its reported geometry - trigger _refine_oversized_badge_crop() instead.
BADGE_SIZE_ANOMALY_RATIO = 1.3

# Real badge sizes measured across 24 confirmed-clean same-row badge pairs
# (2026-07-06, job 8c10092ac4a9 match 1) - used as candidate window sizes
# for the local recovery search in _refine_oversized_badge_crop().
REFINE_SIZE_OPTIONS = [(33, 32), (37, 36), (41, 40)]
# How far beyond the malformed box's own bounds to search - generous on
# purpose, since the real badge inside a merged blob isn't guaranteed to be
# offset in only one direction (see module docstring).
REFINE_SEARCH_MARGIN_PX = 25
REFINE_SEARCH_STEP_PX = 2

_TEMPLATE_CACHE = None   # {type_name: [gray_template_array, ...]}
_SPECIES_TYPES_CACHE = None


def load_type_templates(templates_dir=TEMPLATES_DIR):
    """Loads every real captured badge template in `templates_dir`, grouped
    by type name (a template file may be named "type_fire.png" or
    "type_fire_b.png" - the "_b" etc. suffix marks a second real reference
    crop of the SAME type from a different row/instance, kept as an
    additional candidate to match against rather than picking just one).
    Cached after the first call. Returns {} (not an error) if the directory
    doesn't exist yet."""
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE is not None:
        return _TEMPLATE_CACHE
    _TEMPLATE_CACHE = {}
    if not os.path.isdir(templates_dir):
        return _TEMPLATE_CACHE
    for fname in sorted(os.listdir(templates_dir)):
        if not fname.startswith("type_") or not fname.lower().endswith(".png"):
            continue
        type_name = fname[len("type_"):].rsplit(".", 1)[0]
        type_name = type_name[:-2] if type_name.endswith("_b") else type_name
        img = cv2.imread(os.path.join(templates_dir, fname), cv2.IMREAD_COLOR)
        if img is None:
            continue
        gray = cv2.cvtColor(cv2.resize(img, MATCH_SIZE, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        _TEMPLATE_CACHE.setdefault(type_name, []).append(gray)
    return _TEMPLATE_CACHE


def load_species_types(path=SPECIES_TYPES_PATH):
    """Loads accuracy_addons/data/species_types.json (species -> sorted list
    of real Pokemon types, built from PokeAPI - see build script referenced
    in ARCHITECTURE_HANDOFF.md) - cached after the first call. Returns {}
    (not an error) if the file doesn't exist yet."""
    global _SPECIES_TYPES_CACHE
    if _SPECIES_TYPES_CACHE is not None:
        return _SPECIES_TYPES_CACHE
    if not os.path.exists(path):
        _SPECIES_TYPES_CACHE = {}
        return _SPECIES_TYPES_CACHE
    with open(path, encoding="utf-8") as f:
        _SPECIES_TYPES_CACHE = json.load(f)
    return _SPECIES_TYPES_CACHE


def _background_mask(bgr):
    """Same hue/brightness background segmentation as
    species_icon_matcher._tight_crop_to_sprite - returns a uint8 0/255
    foreground mask (255 = likely real content, not panel background)."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    h_deg = h.astype(np.float32) * 2
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
    return fg_clean


def find_badge_components(row_bgr, top_fraction=BADGE_SEARCH_TOP_FRACTION,
                           max_badges=MAX_BADGES_PER_ROW):
    """Finds up to `max_badges` real badge-icon bounding boxes within the TOP
    `top_fraction` of one row band (from slice_badge_rows) - restricting to
    the top excludes the gender icon that sits below the badges. Uses the
    same background mask as species_icon_matcher, then filters connected
    components by minimum size (MIN_BADGE_SIDE_PX in both dimensions) AND
    aspect ratio (MIN/MAX_BADGE_ASPECT_RATIO) - the aspect-ratio filter is a
    real fix for a real found artifact (see module docstring). Returns a
    list of (x, y, w, h) bounding boxes in `row_bgr`'s own pixel space,
    sorted left to right - NOT cropped images themselves (callers slice
    row_bgr[y:y+h, x:x+w] as needed)."""
    if row_bgr is None or row_bgr.size == 0:
        return []
    h_total = row_bgr.shape[0]
    search_h = max(1, int(h_total * top_fraction))
    band = row_bgr[:search_h, :]
    fg = _background_mask(band)
    n_components, _labels, stats, _centroids = cv2.connectedComponentsWithStats(fg, connectivity=8)
    boxes = []
    for i in range(1, n_components):
        x, y, w, hc, _area = stats[i]
        if w < MIN_BADGE_SIDE_PX or hc < MIN_BADGE_SIDE_PX:
            continue
        ratio = w / float(hc)
        if not (MIN_BADGE_ASPECT_RATIO <= ratio <= MAX_BADGE_ASPECT_RATIO):
            continue
        boxes.append((x, y, w, hc))
    boxes.sort(key=lambda b: b[0])
    return boxes[:max_badges]


def slice_badge_rows(column_crop_bgr, max_rows=MAX_ROWS, row_top_frac=ROW_TOP_FRAC,
                      row_height_frac=ROW_HEIGHT_FRAC):
    """Divides ONE crop_opponent_badge_column()-style image into up to
    `max_rows` per-Pokemon row bands (BGR), top to bottom - same row-position
    math as species_icon_matcher.slice_sprite_crops (see that function and
    this module's docstring for why the constants transfer). A row past the
    bottom of the crop, or that looks empty/background-only, is None -
    callers should treat None as "no data," never as "this slot is empty in-
    game" (a team preview always shows exactly team_size Pokemon).

    `row_top_frac`/`row_height_frac` default to this module's own ROW_TOP_
    FRAC/ROW_HEIGHT_FRAC (measured from a portrait mobile recording - see
    those constants' own comment), but callers may override both when the
    source crop's own geometry doesn't match that measurement - concretely,
    analyze_matches.badge_column_geometry() passes a different pair for a
    landscape-oriented video, where the portrait-tuned defaults were found
    (2026-07-08) to misalign every row band even after the crop BOX itself
    was corrected for the different aspect ratio, since they also encode a
    specific "header gap before row 1" proportion that a differently-
    cropped box doesn't share. See analyze_matches.py's
    LANDSCAPE_OPPONENT_BADGE_COLUMN_BOX comment for the full real-footage
    story and validation."""
    if column_crop_bgr is None or column_crop_bgr.size == 0:
        return [None] * max_rows
    h, w = column_crop_bgr.shape[:2]
    row_top = row_top_frac * h
    row_height = row_height_frac * h
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
        out.append(row_img)
    return out


def identify_badge_type(badge_bgr, templates=None, min_score=MIN_BADGE_MATCH_SCORE, top_k=3):
    """Compares one isolated badge crop (from a find_badge_components box)
    against every loaded type template (load_type_templates(), grouped by
    type - each type may have more than one real reference crop, and this
    takes the BEST-scoring one per type) and returns the top `top_k`
    (score, type_name) matches, sorted best-first. Returns [] if `badge_bgr`
    is empty/None or no templates are loaded (e.g. the template directory
    hasn't been populated). See module docstring for MIN_BADGE_MATCH_SCORE's
    real grounding - this does NOT filter by it itself (that's
    identify_row_types' job, since a caller comparing raw scores across
    several badges may want the unfiltered ranking)."""
    if badge_bgr is None or badge_bgr.size == 0:
        return []
    templates = templates if templates is not None else load_type_templates()
    if not templates:
        return []
    badge_small = cv2.resize(badge_bgr, MATCH_SIZE, interpolation=cv2.INTER_AREA)
    badge_gray = cv2.cvtColor(badge_small, cv2.COLOR_BGR2GRAY)
    scores = []
    for type_name, refs in templates.items():
        best = max(
            float(cv2.matchTemplate(badge_gray, ref, cv2.TM_CCOEFF_NORMED)[0][0])
            for ref in refs
        )
        scores.append((best, type_name))
    scores.sort(key=lambda t: t[0], reverse=True)
    return scores[:top_k]


_TEMPLATE_COLOR_CACHE = None   # {type_name: average_bgr_ndarray}


def _average_color(bgr_img):
    """Mean BGR color across an image, resized to MATCH_SIZE first for the
    same size-invariance reason identify_badge_type resizes before
    grayscale template matching - this is the color-signal counterpart to
    that function, which discards color entirely by converting to
    grayscale. Returns a 3-element numpy array (B, G, R), each 0-255."""
    small = cv2.resize(bgr_img, MATCH_SIZE, interpolation=cv2.INTER_AREA)
    return small.reshape(-1, 3).mean(axis=0)


def _color_similarity(crop_color, ref_color):
    """0-1 similarity from Euclidean BGR distance between two average
    colors (see _average_color), scaled by COLOR_DISTANCE_SCALE - that
    constant's own comment has the real measured same-type/different-type
    distance distributions this scaling is grounded in."""
    dist = float(np.linalg.norm(crop_color - ref_color))
    return max(0.0, 1.0 - dist / COLOR_DISTANCE_SCALE)


def load_type_template_colors(templates_dir=TEMPLATES_DIR):
    """Loads the average BGR color of every real captured badge template,
    grouped by type name (averaged across multiple ref crops of the same
    type, e.g. "type_fire.png" + "type_fire_b.png") - the color-signal
    counterpart to load_type_templates(), which only keeps a grayscale
    version for shape matching. Cached after the first call. Returns {}
    (not an error) if the directory doesn't exist yet."""
    global _TEMPLATE_COLOR_CACHE
    if _TEMPLATE_COLOR_CACHE is not None:
        return _TEMPLATE_COLOR_CACHE
    _TEMPLATE_COLOR_CACHE = {}
    if not os.path.isdir(templates_dir):
        return _TEMPLATE_COLOR_CACHE
    per_type = {}
    for fname in sorted(os.listdir(templates_dir)):
        if not fname.startswith("type_") or not fname.lower().endswith(".png"):
            continue
        type_name = fname[len("type_"):].rsplit(".", 1)[0]
        type_name = type_name[:-2] if type_name.endswith("_b") else type_name
        img = cv2.imread(os.path.join(templates_dir, fname), cv2.IMREAD_COLOR)
        if img is None:
            continue
        per_type.setdefault(type_name, []).append(_average_color(img))
    _TEMPLATE_COLOR_CACHE = {t: np.mean(cs, axis=0) for t, cs in per_type.items()}
    return _TEMPLATE_COLOR_CACHE


def identify_badge_type_with_color(badge_bgr, templates=None, template_colors=None,
                                    min_score=MIN_BADGE_MATCH_SCORE, top_k=3):
    """Same ranking as identify_badge_type(), plus a real, measured color
    cross-check (see COLOR_DISTANCE_SCALE/COLOR_AGREEMENT_FLOOR/
    COLOR_BONUS_MAX for the grounding, and the module docstring's 2026-07-08
    UPDATE for the full real-data validation story) applied ONLY as an
    ADDITIVE bonus on the score of whichever type identify_badge_type()
    already guessed - a badge whose average color ALSO closely matches that
    same guessed type's reference color gets a small bonus (capped at
    COLOR_BONUS_MAX), but a shape score is NEVER reduced for a disagreeing
    color. This guarantees a badge that already clears MIN_BADGE_MATCH_SCORE
    on shape alone can never be pushed back below it here - re-verified
    directly against all 56 real badge instances available at the time this
    was built: 0 regressions. Real result on the two previously-ambiguous
    slots this was hoped to resolve: it did NOT resolve either one (color's
    own independent opinion disagreed with shape's weak guess in both
    cases, so no bonus applied) - see the module docstring for the honest
    full story, including a real, actionable side-finding (one of those two
    slots' color consistently points to Ground, an already-covered type,
    rather than confirming it as a new one)."""
    ranked = identify_badge_type(badge_bgr, templates=templates, min_score=min_score, top_k=top_k)
    if not ranked:
        return ranked
    template_colors = template_colors if template_colors is not None else load_type_template_colors()
    if not template_colors:
        return ranked
    crop_color = _average_color(badge_bgr)
    boosted = []
    for score, type_name in ranked:
        ref_color = template_colors.get(type_name)
        if ref_color is None:
            boosted.append((score, type_name))
            continue
        color_sim = _color_similarity(crop_color, ref_color)
        bonus = (max(0.0, color_sim - COLOR_AGREEMENT_FLOOR) / (1.0 - COLOR_AGREEMENT_FLOOR)) * COLOR_BONUS_MAX
        boosted.append((min(1.0, score + bonus), type_name))
    boosted.sort(key=lambda t: t[0], reverse=True)
    return boosted


def _refine_oversized_badge_crop(row_bgr, box, templates=None):
    """Recovery search for a badge whose detected box was flagged as an
    anomalous connected-component merge (see BADGE_SIZE_ANOMALY_RATIO and
    the module docstring's ROOT CAUSE section) - the real badge pixels are
    somewhere inside (or just outside the edge of) the malformed box, so
    this slides each of REFINE_SIZE_OPTIONS across a REFINE_SEARCH_MARGIN_PX
    margin around the box and keeps whichever sub-crop scores best against
    ANY loaded template. Returns (best_score, best_type_name) - (0.0, None)
    if no templates are loaded or the box is degenerate.

    This is deliberately a SEPARATE step from identify_badge_type (which
    only ever scores the box it's given) - identify_row_types decides WHEN
    to call this (only for a box already flagged anomalous), so the normal,
    already-clean case never pays this extra cost."""
    if row_bgr is None or row_bgr.size == 0:
        return (0.0, None)
    templates = templates if templates is not None else load_type_templates()
    if not templates:
        return (0.0, None)
    x, y, w, h = box
    row_h, row_w = row_bgr.shape[:2]
    best_score, best_type = 0.0, None
    for cw, ch in REFINE_SIZE_OPTIONS:
        x_lo = max(0, x - REFINE_SEARCH_MARGIN_PX)
        x_hi = min(row_w - cw, x + w + REFINE_SEARCH_MARGIN_PX)
        y_lo = max(0, y - REFINE_SEARCH_MARGIN_PX)
        y_hi = min(row_h - ch, y + h + REFINE_SEARCH_MARGIN_PX)
        if x_hi < x_lo or y_hi < y_lo:
            continue
        for xx in range(x_lo, x_hi + 1, REFINE_SEARCH_STEP_PX):
            for yy in range(y_lo, y_hi + 1, REFINE_SEARCH_STEP_PX):
                crop = row_bgr[yy:yy + ch, xx:xx + cw]
                ranked = identify_badge_type(crop, templates=templates, top_k=1)
                if ranked and ranked[0][0] > best_score:
                    best_score, best_type = ranked[0][0], ranked[0][1]
    return (best_score, best_type)


def identify_row_types(row_bgr, min_score=MIN_BADGE_MATCH_SCORE, use_color_check=False):
    """High-level, one-row convenience: finds badge components
    (find_badge_components), identifies each one (identify_badge_type),
    keeping only matches clearing `min_score`. Returns
    {"num_badges_found": int, "identified_types": [str, ...]} -
    `num_badges_found` is the number of real badge-SHAPED components located
    (regardless of whether each one was confidently classified), which
    matters for narrow_species_by_types (see that function's docstring for
    why this is a distinct, useful signal from `identified_types`'s own
    length).

    When exactly 2 badge boxes are found and the second (rightmost) one is
    anomalously larger than the first (BADGE_SIZE_ANOMALY_RATIO - a real,
    diagnosed connected-component merge failure, see module docstring's
    ROOT CAUSE section), this calls _refine_oversized_badge_crop() to
    recover the real badge pixels instead of scoring the malformed box
    directly - real re-validation found this fixes the large majority of
    a previously-persistent per-badge miss without introducing any new
    safety violations (see module docstring).

    `use_color_check` (default False, preserving this function's original
    behavior exactly) switches the per-badge scoring from identify_badge_type
    to identify_badge_type_with_color - see that function's own docstring
    and the module docstring's 2026-07-08 UPDATE for the real validation
    behind it. Default is False rather than True because the real-data test
    found it resolves zero additional badges on its own (though it also
    causes zero regressions) - it's kept available as an opt-in rather than
    made the default until it demonstrates a real accuracy win, per this
    module's own "don't trust an untested improvement" pattern."""
    boxes = find_badge_components(row_bgr)
    identified = []
    templates = load_type_templates()
    scorer = identify_badge_type_with_color if use_color_check else identify_badge_type
    if len(boxes) == 2:
        (x0, y0, w0, h0), (x1, y1, w1, h1) = boxes
        r0 = scorer(row_bgr[y0:y0 + h0, x0:x0 + w0], templates=templates, top_k=1)
        if r0 and r0[0][0] >= min_score:
            identified.append(r0[0][1])
        if w1 > w0 * BADGE_SIZE_ANOMALY_RATIO or h1 > h0 * BADGE_SIZE_ANOMALY_RATIO:
            score, ttype = _refine_oversized_badge_crop(row_bgr, (x1, y1, w1, h1), templates=templates)
            if ttype is not None and score >= min_score:
                identified.append(ttype)
        else:
            r1 = scorer(row_bgr[y1:y1 + h1, x1:x1 + w1], templates=templates, top_k=1)
            if r1 and r1[0][0] >= min_score:
                identified.append(r1[0][1])
    else:
        for (x, y, w, h) in boxes:
            crop = row_bgr[y:y + h, x:x + w]
            ranked = scorer(crop, templates=templates, top_k=1)
            if ranked and ranked[0][0] >= min_score:
                identified.append(ranked[0][1])
    return {"num_badges_found": len(boxes), "identified_types": identified}


def identify_row_types_multi_frame(row_bgr_list, min_score=MIN_BADGE_MATCH_SCORE,
                                    min_frame_agreement=None, use_color_check=False):
    """Combines identify_row_types() across SEVERAL real crops of the SAME
    row (same Pokemon, same static team-preview screen) from different
    frames - the concrete fix for the real frame-sensitivity finding
    documented in the module docstring (single-frame full both-badge
    identification varied 3/6-5/6 across 7 real frames of one match, even
    though the same static screen was on-screen the whole time).

    `use_color_check` (default False) is forwarded unchanged to every
    per-frame identify_row_types() call - see that function's own
    docstring for what it does (additive-only color bonus on top of the
    shape score) and the module docstring's 2026-07-08 UPDATE for why it
    doesn't move the needle in isolation on the one match it's been
    measured against so far. It's wired through here (rather than left
    single-frame-only) because analyze_matches.py's attach_opponent_type_
    hints() calls this multi-frame path, not identify_row_types()
    directly, in production.

    `row_bgr_list` should be several independently-sampled crops of one
    row (e.g. from `slice_badge_rows()` output at several different
    timestamps within the same team-preview window) - None entries are
    skipped. Each frame is scored independently via identify_row_types(),
    then combined by MAJORITY VOTE:
      - a type only makes it into the final `identified_types` if it was
        confidently identified in at least `min_frame_agreement` of the
        frames. Default (when left None): min((n // 2) + 1,
        MAX_FRAME_AGREEMENT_CAP) - a simple majority for a small/
        homogeneous batch, but CAPPED at a small absolute number for a
        large pooled batch, so a real signal that only appears in a
        handful of frames out of a large, mostly-irrelevant pool (see
        MAX_FRAME_AGREEMENT_CAP's own comment for the real 2026-07-08
        production regression this fixes) isn't diluted into never
        reaching majority. A type that only one noisy frame happened to
        misread is still filtered out either way, rather than trusting
        whichever single frame a caller picked.
      - `num_badges_found` is the most common (mode) badge count seen
        across frames, tie-broken toward the LARGER count. This tie-break
        direction is deliberate: narrow_species_by_types' EXACT-match rule
        for num_badges_found<=1 would wrongly EXCLUDE a real dual-typed
        species if this value is under-counted (assumed mono when it's
        really dual) - the weaker "partial contains" rule used for a
        2-badges/1-classified read is over-inclusive instead, which keeps
        the real species safe even if it doesn't narrow as far. Favoring
        the larger count on a tie protects the safety property the module
        is actually built around (see HONEST CURRENT SCOPE).

    Returns {"num_badges_found": int, "identified_types": [str, ...],
    "n_frames_used": int, "type_votes": {type: count}, "badge_count_votes":
    {count: n_frames}} - the vote breakdowns are included so callers/tests
    can see WHY a type was or wasn't confirmed, not just the final answer.
    The first two keys match identify_row_types()'s own return shape, so
    this result can be passed straight into narrow_species_by_types()
    unchanged."""
    frame_results = [identify_row_types(r, min_score=min_score, use_color_check=use_color_check)
                     for r in row_bgr_list if r is not None]
    n = len(frame_results)
    if n == 0:
        return {"num_badges_found": 0, "identified_types": [], "n_frames_used": 0,
                "type_votes": {}, "badge_count_votes": {}}
    if min_frame_agreement is None:
        min_frame_agreement = min((n // 2) + 1, MAX_FRAME_AGREEMENT_CAP)

    type_votes = {}
    for res in frame_results:
        for t in res["identified_types"]:
            type_votes[t] = type_votes.get(t, 0) + 1
    confirmed_types = sorted(t for t, count in type_votes.items() if count >= min_frame_agreement)

    badge_count_votes = {}
    for res in frame_results:
        c = res["num_badges_found"]
        badge_count_votes[c] = badge_count_votes.get(c, 0) + 1
    # Mode, tie-broken toward the larger badge count (see docstring above).
    consensus_badge_count = max(badge_count_votes.items(), key=lambda kv: (kv[1], kv[0]))[0]

    return {
        "num_badges_found": consensus_badge_count,
        "identified_types": confirmed_types,
        "n_frames_used": n,
        "type_votes": type_votes,
        "badge_count_votes": badge_count_votes,
    }


def narrow_species_by_types(identified_types, num_badges_found, candidate_species_types=None):
    """Filters a species->types mapping (defaults to
    accuracy_addons/data/species_types.json's full legal roster - pass a
    pre-filtered dict, e.g. just the current regulation's roster, for a
    tighter/faster search) down to species consistent with one row's
    identify_row_types() result. Returns a sorted list of candidate species
    names (NOT guaranteed to be exactly one - see module docstring).

    The narrowing rule depends on `num_badges_found` vs. len(identified_types):
      - num_badges_found == 1 (a real mono-type Pokemon - only one badge
        SLOT was filled at all): requires an EXACT single-type match - a
        species with 2 real types can never be the right answer here,
        because a truly dual-typed Pokemon always shows two badges in this
        UI, confirmed by real footage (e.g. Blastoise, mono Water, shows
        only one badge, right-aligned into the second slot position).
      - num_badges_found == 2 and both were classified: requires an EXACT
        match on the unordered pair of types (species must be dual-typed
        with precisely these two types, in either order).
      - num_badges_found == 2 but only one was classified (the other badge
        is a real icon that just isn't in TEMPLATES_DIR yet, or scored below
        MIN_BADGE_MATCH_SCORE): only requires the species to CONTAIN the one
        identified type (partial match) - the second, unidentified type
        could be any of the 4 not-yet-covered types, so this can't be
        narrowed further without more coverage.
      - identified_types is empty: returns every candidate unfiltered (no
        real signal to narrow by) - callers should treat this the same as
        "narrowing didn't help this row," not as a positive multi-species
        result.
    """
    types_map = candidate_species_types if candidate_species_types is not None else load_species_types()
    if not identified_types:
        return sorted(types_map)
    wanted = set(identified_types)

    if num_badges_found <= 1:
        return sorted(sp for sp, types in types_map.items() if set(types) == wanted)

    if len(identified_types) >= 2:
        return sorted(sp for sp, types in types_map.items() if set(types) == wanted)

    # Exactly one of two real badges was confidently classified.
    return sorted(sp for sp, types in types_map.items() if wanted.issubset(set(types)))
