"""
Tiered accuracy layer for analyze_matches.py's live mode (--use-ocr-tier):
before merging into the existing Gemini-derived events, this reads the
deterministic on-screen text directly via OCR (ocr_battle_reader.py +
battle_text_parser.py) and resolves any Pokemon nickname it encounters via
pokemon_identity.py. This is what "tiered pipeline: cheap/deterministic
first, expensive vision only for genuine ambiguous leftovers" (the goal
discussed when this feature was proposed) actually means in code: text
that's exact and free to read gets read for free, and a real (cheap, ONE-
per-Pokemon) vision call is only spent on the one thing text truly can't
resolve on its own - a player-chosen nickname.

Honest current scope, stated plainly rather than implied:
  - Wired into analyze_matches.py's LIVE mode only (--use-ocr-tier), not
    --use-batch-api yet - batch mode's whole design defers all frame
    sampling to phase 2/3 in a way this hasn't been threaded through (see
    ARCHITECTURE_HANDOFF.md). Left as a documented gap, not silently unsupported.
  - Reads the bottom narration banner only (move_used, fainted, crits,
    effectiveness, status, stat changes, sends-out, weather/terrain,
    battle_end phrasing) - see battle_text_parser.py's exact coverage.
    Board state (field_state, hp_change, ability/item callouts that float
    near a sprite instead of the banner) is NOT covered here at all and
    still comes entirely from the existing Gemini read.
  - Does NOT replace the existing Gemini battle-frame read - it
    supplements it. A Gemini-derived event that clearly duplicates an
    OCR-derived one (same event type + same Pokemon + close in time) is
    dropped in favor of the OCR one (deterministic text beats a vision
    guess about the same moment), but Gemini stays the only source for
    everything OCR doesn't target.
  - Costs at most one extra Gemini vision call PER DISTINCT NICKNAME seen
    in a match (typically zero - most Pokemon aren't nicknamed), not one
    per frame - see pokemon_identity.py.
"""

import cv2

import battle_text_parser as btp
import ocr_battle_reader as ocr
from pokemon_identity import IdentityResolver  # noqa: F401  (re-exported for callers)

# Denser and higher-resolution than the Gemini battle sampling
# (args.battle_fps / args.frame_width default to ~0.33fps / 640px, tuned to
# keep Gemini's per-image cost down) - a text banner is only on screen
# briefly, and small on-screen text needs real resolution to read at all
# (see ocr_battle_reader.py's docstring on the native-vs-downscaled
# tradeoff). This is a SEPARATE sampling pass, so it has no effect on
# Gemini's own cost/frame count.
OCR_FPS = 2.0
OCR_SCALE_W = 1280

IDENTITY_PROMPT = (
    "This image shows a moment from a Pokemon VGC doubles battle. Look at the Pokemon named "
    "'{display_name}' in this frame (check its on-screen name plate to find which one that is) "
    "and identify its actual SPECIES by appearance (sprite/silhouette) - the name text may be a "
    "player-chosen NICKNAME, not the species, so do not just repeat it back. "
    'Return ONLY JSON: {{"species": "<the real species name>"}}.')


def _same_actor_or_unknown(a, b):
    """True unless BOTH sides are positively known and DIFFERENT. Mirror
    matches (same species on both sides) can produce two genuinely separate
    events - e.g. both players' Whimsicott using Protect within the same
    couple seconds - that must never collapse into one just because the
    species/event/detail text matches. `actor` is only trusted as a
    disambiguator when both events actually have it set (battle_text_parser
    only sets `actor` when the banner text itself discloses a side - see its
    own module docstring point 2 - so it's frequently None); when either
    side is unknown, this falls back to the old species/event/timestamp-only
    behavior rather than risk splitting a genuine duplicate apart."""
    if a and b:
        return a == b
    return True


def _dedupe_consecutive(events, window_s=3.0):
    """Collapses repeats of the identical (event, pokemon, detail) seen
    within `window_s` seconds of each other into one kept event. A text
    banner stays on screen across several consecutive OCR-sampled frames -
    without this, every one of those frames would separately re-report the
    exact same action as if it were a new event each time.

    Does NOT collapse across different, known-distinct actors - see
    _same_actor_or_unknown - so a mirror match (both sides sharing a
    species) can't have one side's real event silently swallowed as a
    "repeat" of the other side's near-simultaneous one."""
    out = []
    for e in sorted(events, key=lambda e: e["timestamp"]):
        dup = False
        for kept in reversed(out):
            if e["timestamp"] - kept["timestamp"] > window_s:
                break
            if (kept.get("event") == e.get("event")
                    and kept.get("pokemon") == e.get("pokemon")
                    and kept.get("detail") == e.get("detail")
                    and _same_actor_or_unknown(kept.get("actor"), e.get("actor"))):
                dup = True
                break
        if not dup:
            out.append(e)
    return out


def sample_ocr_frames(sample_window_fn, ffmpeg, video, start, end, workdir, hwaccel=""):
    """Just the OCR-tier sampling step (OCR_FPS/OCR_SCALE_W) - split out from
    extract_ocr_events() so a caller that also wants the raw, denser/higher-
    res frame list for something ELSE (see analyze_matches.
    attach_reference_frames' `quality_frames` parameter, added to let the
    free accuracy_addons pixel cross-checks read from these sharper frames
    too, not just OCR-sourced events) doesn't have to sample the exact same
    match window twice. `sample_window_fn` is passed in for the same reason
    documented on extract_ocr_events below - callers pass
    analyze_matches.sample_window."""
    return sample_window_fn(ffmpeg, video, start, end - start, OCR_FPS,
                             workdir, "ocr", hwaccel, scale_w=OCR_SCALE_W)


def extract_ocr_events(sample_window_fn, ffmpeg, video, start, end, workdir, hwaccel="", frames=None):
    """Samples the match window at OCR_FPS/OCR_SCALE_W (a separate, higher-
    res pass from the one built for Gemini - see module docstring), reads
    the bottom banner off every frame, and parses whatever text is legible
    into structured events via battle_text_parser. Returns a deduped list
    of events, each carrying its own reference_frame + source="ocr" (every
    event's confidence already comes from battle_text_parser, which rates
    a clean deterministic text match as MORE trustworthy than a vision
    guess - see LOW_CONFIDENCE_THRESHOLD in MatchEvents.jsx).

    `sample_window_fn` is passed in (rather than imported directly) instead
    of importing analyze_matches.sample_window at module load time - that
    would make this module and analyze_matches.py import each other
    (analyze_matches imports this module to use it), which Python can't
    resolve. Callers just pass analyze_matches.sample_window.

    `frames` - if the caller already sampled this exact window via
    sample_ocr_frames() (e.g. to also pass the raw list elsewhere), pass it
    here to avoid re-sampling/re-running ffmpeg for the same window; when
    omitted (the original, still-supported call shape), this samples it
    internally exactly as before."""
    frames = frames if frames is not None else sample_ocr_frames(
        sample_window_fn, ffmpeg, video, start, end, workdir, hwaccel)
    events = []
    for path, ts in frames:
        frame = cv2.imread(path)
        if frame is None:
            continue
        text = ocr.read_bottom_banner(frame)
        if not text:
            continue
        event = btp.parse_line(text)
        if not event:
            continue
        event["timestamp"] = round(ts, 1)
        event["reference_frame"] = path
        event["source"] = "ocr"
        events.append(event)
    return _dedupe_consecutive(events)


def resolve_ocr_pokemon_names(events, resolver, vision_call=None):
    """For every OCR event naming a Pokemon, resolves its display name to
    the real species via `resolver` (an IdentityResolver seeded with this
    match's known roster - see pokemon_identity.py). A name that doesn't
    fuzzy-match anything known is flagged as needing real identification;
    if `vision_call` (a callable: (display_name, reference_frame_path) ->
    species string or None) is given, it's invoked ONCE for that flagged
    name and the result is cached via resolver.learn() so the SAME nickname
    is never re-flagged for the rest of this match. If `vision_call` is
    None (no API client available) or it fails/returns nothing, the event
    keeps its originally-read name but has its confidence dropped - the
    same "never silently force a guess, flag it instead" pattern
    build_event_prompt already uses for Gemini's own roster-mismatch case.
    Mutates and returns `events`."""
    for e in events:
        name = e.get("pokemon")
        if not name:
            continue
        species, needs_vision = resolver.resolve_or_flag(name)
        if species:
            e["pokemon"] = species
            continue
        if needs_vision and vision_call is not None:
            try:
                species = vision_call(name, e.get("reference_frame"))
            except Exception:
                species = None
            if species:
                resolver.learn(name, species)
                e["pokemon"] = species
                continue
        e["confidence"] = min(e.get("confidence", 1.0), 0.3)
        e["detail"] = ((e.get("detail") or "") +
                       f" [unresolved nickname: could not identify '{name}']").strip()
    return events


def identify_pokemon_species(call_fn, display_name, image_path):
    """A single real Gemini vision call to resolve one nickname's actual
    species from the frame it appeared in - see module docstring's "ONE
    vision call per Pokemon, not per frame" design and pokemon_identity.py.

    `call_fn` is a (prompt, paths) -> parsed_json callable - callers pass
    something like `functools.partial(analyze_matches.call, client, model)`,
    already bound to a real client/model, so this module never has to know
    what a genai client even is (keeps it import-light and easy to test
    with a fake call_fn). Returns the species string, or None if the call
    fails, the image is missing, or nothing usable comes back - callers
    should treat None as "still unresolved", not an error."""
    if not image_path:
        return None
    try:
        data = call_fn(IDENTITY_PROMPT.format(display_name=display_name), [image_path])
    except Exception:
        return None
    if isinstance(data, dict):
        species = data.get("species")
        if species:
            return str(species).strip()
    return None


def merge_ocr_and_vision_events(ocr_events, vision_events, window_s=4.0):
    """Combines OCR-derived events (deterministic text reads) with the
    existing Gemini vision-derived events for one match, dropping any
    vision event that's clearly a duplicate of one already captured via
    OCR (same event type + same Pokemon, within `window_s` seconds) in
    favor of the OCR version. Vision events covering anything OCR doesn't
    target at all (field_state, hp_change, most items/abilities near a
    sprite rather than in the banner, team_preview, battle_end) are passed
    through untouched - this is a supplement, not a replacement (see
    module docstring). Never drops a vision event in favor of an OCR one
    when the two are positively known to be on DIFFERENT sides (see
    _same_actor_or_unknown) - a mirror match where both players are running
    the same species must not have one side's real vision-derived event
    dropped just because the other side's OCR-derived event for that same
    species landed nearby in time. Returns a new list sorted by timestamp."""
    def _ts(e):
        try:
            return float(e.get("timestamp"))
        except (TypeError, ValueError):
            return None

    def is_duplicate(vision_e):
        v_ts = _ts(vision_e)
        if v_ts is None:
            return False
        for oe in ocr_events:
            if (oe.get("event") == vision_e.get("event")
                    and oe.get("pokemon") == vision_e.get("pokemon")
                    and abs(oe["timestamp"] - v_ts) <= window_s
                    and _same_actor_or_unknown(oe.get("actor"), vision_e.get("actor"))):
                return True
        return False

    kept_vision = [e for e in vision_events if not is_duplicate(e)]
    merged = ocr_events + kept_vision
    merged.sort(key=lambda e: _ts(e) or 0.0)
    return merged
