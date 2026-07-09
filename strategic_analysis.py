"""
strategic_analysis.py - the heuristic layer the user's wider architecture
spec calls the "strategic analysis engine": a per-turn advantage score, a
momentum timeline (with plain-language reasons), a resource-tracking summary
(alive-Pokemon count per side over time), and conservative mistake-CANDIDATE
flagging. Built entirely on top of decision_windows.py's per-turn snapshots
plus events.json directly - no new data collection, works on both video- and
Showdown-sourced matches (Showdown matches only started producing the
field_state/turn events this needs as of the 2026-07-04 showdown_import.py
turn-tracking fix - see ARCHITECTURE_HANDOFF.md section 8c).

HONEST SCOPE - read this before trusting a number out of here:
  - Every score in this module is a HAND-TUNED HEURISTIC, not a trained or
    statistically calibrated model. "win_probability" here means "a bounded,
    monotonic function of a simple advantage score," NOT "in similar
    real-world positions, the win rate was X%." A coach's gut-feel momentum
    read is a fair mental model for what these numbers are; a solved-game
    probability is not. This distinction must never be blurred if/when this
    is ever surfaced to a user - the same caution the spec itself repeats.
  - The advantage score's dominant signal is alive-Pokemon-count differential
    (a real, well-understood VGC heuristic - being up a Pokemon is usually a
    bigger positional swing than any single turn's move choice), with a
    smaller Tailwind bonus layered on when a field_state event actually
    reports it. Trick Room, weather, and terrain are NOT scored - they
    modify who's effectively "faster," which depends on the actual Pokemon
    on the field and their base speeds (data this project doesn't track),
    so attributing a fixed bonus to either side would be a guess dressed up
    as a number. They're surfaced as plain narrative facts in `reasons`
    instead (e.g. "Trick Room is active"), never folded into the score.
  - HP-percent-based scoring (added 2026-07-05): compute_advantage_score can
    optionally fold in a small, bounded adjustment from `_turn_hp_snapshot`'s
    average-of-known HP percent per side, gated behind BOTH sides having at
    least one known HP value among their currently-alive roster for that
    turn - a turn with no hp_change data yet (or a match with none at all)
    simply gets no HP adjustment, never a guessed 100%. `hp_percent` is a
    single-Pokemon EVENT field (see adapters/pokemon/game.json), not a
    field_state field, so this is assembled turn-by-turn from `hp_change`
    events rather than read directly off any one event - see
    `_turn_hp_snapshot`'s own docstring for the exact "reflects the START of
    the turn" ordering this follows (same convention decision_windows.py's
    own snapshot/outcome ordering uses). Currently ONLY Showdown-sourced
    matches populate this reliably (showdown_import.py's 2026-07-05
    |-damage|/|-heal| parsing gives an EXACT HP fraction on every hit); the
    video/Gemini pipeline's hp_change events are sparse/best-effort (see
    accuracy_addons/hp_bar_reader.py, gated behind --use-accuracy-addons),
    so this adjustment will often simply not fire there - it degrades to
    the pre-2026-07-05 alive-count-only score, never to a fabricated number.
    HP_WEIGHT keeps this a secondary signal (bounded to a max ±HP_WEIGHT*100
    point swing) alongside the dominant alive-Pokemon-count differential - a
    Pokemon at 1% HP is still fully "alive" for the count-based score; this
    only nudges the number toward whichever side's known survivors are
    healthier. Averages every alive Pokemon's known HP equally - does not
    weight by that Pokemon's own max HP/bulk, and says nothing about an
    unrevealed-HP Pokemon at all. Keyed by `_species_key` (Mega/regional-form
    stripped) rather than the raw event species name, so a Mega-evolved
    Pokemon's hp_change events (reported under its post-Mega name) still
    resolve against available_pokemon's base roster name - the same
    Mega-name mismatch class of bug fixed for fainted-tracking in
    decision_windows.py (2026-07-04, task #123), applied here too.
  - Mistake-candidate flagging is intentionally conservative and only ever
    flags a turn as "worth reviewing," never asserts a specific correct
    play was available instead - the same "flag, don't force a guess"
    discipline moveset_validator.py/pokemon_identity.py already hold
    themselves to. Two concrete, checkable patterns are flagged:
      (a) `blind_switch_koed` - a Pokemon switched in and fainted in that
          SAME turn (a real, unambiguous "walked into a KO" pattern).
      (b) `big_momentum_swing` - a turn where the advantage score swings
          sharply against a side (see SWING_THRESHOLD) - flagged for human
          review, not asserted as a proven error, since a big swing can
          also just be a Pokemon successfully executing a good, high-risk
          play that happened to trade down (e.g. a Protect stall that ran
          out, correctly).
  - `infer_win_condition_candidates` (added 2026-07-05) is the same
    conservative "candidate for review" style, applied to "what was this
    side actually playing for": two concrete, checkable patterns, not an
    attempt at a general strategy-reading engine.
      (a) `designated_sweeper` - a Pokemon that received 2+ offensive stat
          boosts (Attack/Sp. Atk/Speed rising) over the match. Relies on
          `stat_change` events carrying a resolvable `actor` - reliable for
          Showdown-sourced matches (showdown_import.py's |-boost|/|-unboost|
          parsing, added alongside this) but NOT for OCR-tier stat_change
          events, since battle_text_parser.py's stat-change regex can't
          determine a side from the banner text alone and leaves `actor`
          None - those events are silently skipped here rather than
          guessed, so this candidate under-detects (never over-detects) on
          video-sourced matches today.
      (b) `primary_closer` - the Pokemon on a side that most often acted on
          a turn the OPPOSING side lost a Pokemon. Deliberately NOT proof
          that its move caused the KO (doubles has 2 actions per side per
          turn, and a faint can come from residual damage/status, not just
          that turn's move) - a correlation worth a human's glance, same
          spirit as `big_momentum_swing`.
  - `identify_threats` (added 2026-07-05) ranks the OPPONENT's revealed
    Pokemon by type-chart danger to the PLAYER's own brought roster - same
    type-chart-only approach as backend/type_synergy.py's team_risk(), just
    pointed the other direction (a Pokemon's own type(s) vs. the player's
    team's weaknesses, rather than a team's weaknesses against itself).
    Can only reason about a Pokemon's known SPECIES TYPE(S)
    (backend/pokedex.SPECIES_TYPES) - there is no move-to-type data
    anywhere in this project today, so this is a team-preview-tier type
    read ("what does this species' own typing threaten"), not an analysis
    of its actual revealed moves. A Pokemon with off-type coverage will be
    under-rated; a Pokemon that never attacks will be over-rated. Each
    revealed Pokemon's `known_moves_seen` (assembled across the whole match,
    not just whichever turn it was last on the board for - see
    `_cumulative_known_moves`) is attached purely as reference context and
    plays NO part in the score.
  - `trace_loss_to_turn` (added 2026-07-05) is the KO-attribution/loss-
    pattern piece: given a match with a definite winner (its own
    `battle_end` event's `winner` field - "unknown"/tied matches are
    skipped, "flag, don't guess"), it finds the LAST turn the losing side
    was still tied or ahead on alive-Pokemon count - by definition that
    turn is never followed by another tied-or-ahead turn, so "the deficit
    that opened up afterward was never recovered" always holds for it, and
    this becomes `decisive_turn`. Two cases are genuinely unclear and
    deliberately return `decisive_turn: None` rather than force an answer:
    the losing side was already behind as of the very first turn recorded
    (too early to pin to a turn), or was tied/ahead all the way through the
    last turn recorded (the loss must have happened after the data ends).
    `final_blow` is purely factual (not inferred): the last turn/species the
    losing side actually lost a Pokemon to before the match ended, straight
    from `_turn_faints`. Same "worth a human's review" spirit as
    `flag_mistake_candidates` and `infer_win_condition_candidates` - this
    identifies WHEN things went wrong, never WHY (no move-quality judgment).
  - Turn boundaries and the alive-Pokemon-count/board data all come directly
    from decision_windows.build_decision_windows(), so this module inherits
    every one of ITS documented limitations too - most notably, a match with
    no field_state/turn events returns an empty timeline (module docstring,
    ARCHITECTURE_HANDOFF.md section 8c).

Pure functions, no video/Gemini/network - same reasoning as decision_windows.py/
skill_scores.py for not importing analyze_matches.py directly (avoids pulling
in heavier deps like gemini_batch/frame_dedup into a backend request path).
"""

import sys
import math
import re
from collections import Counter
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent
if str(_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(_BASE_DIR))

from coach_report import group_by_match, ts
from decision_windows import build_decision_windows, _normalize_turn
from backend import pokedex

ALIVE_WEIGHT = 25          # score points per net Pokemon of "numbers advantage"
TAILWIND_WEIGHT = 10       # score points for having Tailwind up
HP_WEIGHT = 0.15           # score points per point of avg-known-HP-percent differential (max +-15)
SCORE_CLAMP = 100          # advantage score is always in [-SCORE_CLAMP, SCORE_CLAMP]
SWING_THRESHOLD = 40       # |delta| at/above this = a "big momentum swing" flag
WIN_PROB_SOFTNESS = 60.0   # divisor inside tanh() - higher = less confident per point of score
SWEEPER_BOOST_THRESHOLD = 2   # offensive-stat boosts needed for a "designated_sweeper" candidate
CLOSER_COUNT_THRESHOLD = 2    # KO-adjacent turns needed for a "primary_closer" candidate

# --- VGC Battle Intelligence Manual report constants (added 2026-07-09) ---
# See the six compute_*() functions below for the full design rationale of
# each report. Every weight here is a NEW, small, bounded signal that is
# deliberately kept separate from ALIVE_WEIGHT/TAILWIND_WEIGHT/HP_WEIGHT
# above - `score`/compute_advantage_score is left completely unchanged by
# this feature (every existing caller/test keeps getting the exact same
# number), and Position Score composes `score` with these NEW pieces on top
# rather than re-deriving anything `score` already covers - see
# compute_position_score's own docstring for exactly which piece of which
# sub-report is (and is not) folded in, to avoid double-counting.
SPEED_TOOL_WEIGHT = 5       # points per side per revealed speed-control item/ability (Choice Scarf, etc.)
SPEED_SCORE_CLAMP = 30      # compute_speed_control's own score is a small, bounded sub-signal
THREAT_TOOL_WEIGHT = 5      # points per side per revealed danger-move category on the current board
THREAT_SCORE_CLAMP = 30
RESOURCE_SCREEN_WEIGHT = 8  # points per side currently protected by a screen (Reflect/Light Screen/Aurora Veil)
RESOURCE_SCORE_CLAMP = 100  # resource_advantage's descriptive alive+HP score mirrors `score`'s own scale
MOMENTUM_NEUTRAL_BAND = 10  # |delta| at/under this = "neutral" momentum direction

_SIDES = ("player", "opponent")
_SIDE_LABEL = {"player": "Player", "opponent": "Opponent"}

# A small, well-known set of items/abilities that concretely grant a speed
# edge in VGC - NOT an attempt at a full item/ability dex (this project has
# none - see compute_speed_control's own docstring). Matched against
# item_or_ability_activated events' own "ability: X"/"item: X" detail
# convention (see showdown_import.py's -ability/-item handler).
_SPEED_ITEMS = ("choice scarf", "booster energy")
_SPEED_ABILITIES = (
    "speed boost", "unburden", "swift swim", "chlorophyll",
    "sand rush", "slush rush", "surge surfer",
)

# A small, well-known set of VGC doubles moves that concretely hit both
# opposing Pokemon at once ("spread"), redirect an opponent's attack, or
# apply priority disruption - NOT a full move dex (this project has no
# move-to-target/move-to-category data at all - see compute_threat_pressure's
# own docstring). Matched against a Pokemon's own revealed move names.
_SPREAD_MOVES = (
    "rock slide", "heat wave", "muddy water", "surf", "earthquake",
    "discharge", "blizzard", "icy wind", "snarl", "breaking swipe",
    "dazzling gleam", "hyper voice", "eruption", "water spout",
    "boomburst", "electroweb", "glaciate", "sludge wave", "bulldoze",
)
_REDIRECTION_MOVES = ("follow me", "rage powder", "ally switch")

POSITION_SCORE_BANDS = (
    # (low, high, label) - verbatim from the VGC Battle Intelligence Manual.
    (80, 100, "Dominating"),
    (50, 79, "Strong Advantage"),
    (20, 49, "Slight Advantage"),
    (-19, 19, "Even"),
    (-49, -20, "Slight Disadvantage"),
    (-79, -50, "Major Disadvantage"),
    (-100, -80, "Losing"),
)

_REGION_WORDS = r"(?:alolan|alola|galarian|galar|hisuian|hisui|paldean|paldea)"


def _species_key(name):
    """Normalized species key with Mega/regional-form annotations stripped -
    a small local copy of decision_windows._species_key's own normalization
    (kept local rather than imported - same "don't reach into another
    module's private helper" discipline as this module's other local copies,
    e.g. _turn_faints). Needed here for the exact same reason it exists
    there: showdown_import.py's hp_change events report a Mega-evolved
    Pokemon's POST-Mega name ("Kangaskhan" that Mega Evolved reports HP
    updates under "Kangaskhan-Mega"), which never matches available_pokemon's
    base roster name under plain string equality - without this, a Mega'd
    Pokemon's HP updates would silently stop being found the moment it
    Mega Evolved, understating how much HP data is actually known."""
    n = re.sub(r"\(.*?\)", "", str(name or ""))                # "Mawile (Mega)" -> "Mawile "
    n = re.sub(r"(?i)^mega\s+", "", n)                          # "Mega Mawile" -> "Mawile"
    n = re.sub(r"(?i)[\s\-]mega[\s\-][xy]$", "", n)             # "Charizard-Mega-Y" -> "Charizard"
    n = re.sub(r"(?i)[\s\-]mega$", "", n)                       # "Mawile-Mega" -> "Mawile"
    n = re.sub(rf"(?i)^{_REGION_WORDS}\s+", "", n)              # "Alolan Ninetales" -> "Ninetales"
    n = re.sub(rf"(?i)[\s\-]{_REGION_WORDS}$", "", n)           # "Ninetales-Alola" -> "Ninetales"
    return re.sub(r"[^a-z0-9]", "", n.lower())


# Matches the exact "STAT STAGE-WORD" wording both battle_text_parser.py's
# OCR-tier stat_change regex and showdown_import.py's |-boost|/|-unboost|
# handler produce (see showdown_import._STAT_NAMES) - one shared parser
# works on stat_change events from either source.
_STAT_CHANGE_RE = re.compile(
    r"^(Attack|Defense|Sp\. Atk|Sp\. Def|Speed|Accuracy|Evasiveness)\s+"
    r"(sharply rose|harshly fell|rose|fell|won't go any higher|won't go any lower)$"
)
_OFFENSIVE_STATS = {"Attack", "Sp. Atk", "Speed"}


def _parse_stat_change(detail):
    """"Attack rose" -> ("Attack", 1). "Speed harshly fell" -> ("Speed", -1).
    "Accuracy won't go any higher" -> None (already capped - not a real
    change, don't count it as one). None if `detail` doesn't match this
    shared convention at all (e.g. a non-stat_change event's detail, or
    stat_change text from a source that doesn't follow it)."""
    m = _STAT_CHANGE_RE.match(str(detail or "").strip())
    if not m:
        return None
    stat, direction = m.group(1), m.group(2)
    if "rose" in direction:
        return stat, 1
    if "fell" in direction:
        return stat, -1
    return None


def _turn_field_conditions(match_events):
    """turn -> {"tailwind": "player"|"opponent"|"both"|"none"|None,
                "trick_room": True|False|None,
                "weather": str|None, "terrain": str|None, "screens": str|None}
    Read directly off each field_state event's own fields (see
    adapters/pokemon/game.json's fields spec) - only ever what that event
    actually reported, never carried forward or inferred for a turn with no
    field_state of its own. A field left null/"none" in the source event
    stays that way here; callers must treat None as "not reported," not
    "known to be off." """
    out = {}
    for e in match_events:
        if str(e.get("event", "")).strip() != "field_state":
            continue
        t = _normalize_turn(e.get("turn"))
        if t is None:
            continue
        out[t] = {
            "tailwind": e.get("tailwind"),
            "trick_room": e.get("trick_room"),
            "weather": e.get("weather"),
            "terrain": e.get("terrain"),
            "screens": e.get("screens"),
        }
    return out


def _turn_faints(match_events):
    """turn -> {"player": [species,...], "opponent": [species,...]}, keyed by
    the LITERAL turn a pokemon_fainted event occurred in (using the SAME
    forward-assignment convention as decision_windows.py's own turn bucketing
    - a field_state's `turn` sets the "current turn" for every event that
    follows it) - kept as a small local copy here rather than importing
    decision_windows.py's private bucket() closure, which isn't part of its
    public interface.

    Used ONLY by flag_mistake_candidates' blind_switch_koed check, which
    needs to know "did this Pokemon switch in and faint in the SAME literal
    turn" - a different question from build_momentum_timeline's `reasons`,
    which deliberately keys off available_pokemon's diff instead (a faint
    that happens DURING turn N doesn't reduce the alive count, and so
    shouldn't read as a "reason," until turn N+1 - see that function's own
    docstring)."""
    out = {}
    current_turn = None
    for e in match_events:
        kind = str(e.get("event", "")).strip()
        if kind == "field_state":
            t = _normalize_turn(e.get("turn"))
            if t is not None:
                current_turn = t
            continue
        if kind != "pokemon_fainted" or current_turn is None:
            continue
        side = e.get("actor")
        if side not in _SIDES or not e.get("pokemon"):
            continue
        out.setdefault(current_turn, {"player": [], "opponent": []})[side].append(e["pokemon"])
    return out


_HP_FRACTION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*$")


def _coerce_hp_percent(raw):
    """Tolerantly parses a raw hp_percent field into a 0-100 float, or None if
    it can't be read as one - same "skip, don't guess" discipline as every
    other field in this module.

    A real bug this fixes: job 303d13ba0940's `hp_change` events (video/
    vision-extraction sourced, not hand-authored) don't always come back as a
    clean percent number. Match 30 alone has both "20%" (a percent string,
    never converted to a number) and "1/164" (a literal current/max HP-bar
    transcription, never converted to a percent at all). Both are salvageable
    without guessing at the real number, so both are handled here; anything
    else unparseable returns None exactly like a missing hp_percent field
    already did, rather than crashing every consumer that sums this value
    (the real crash this fixed: compute_advantage_score's own sum() raising
    "unsupported operand type(s) for +: 'float' and 'str'" on that match)."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if text.endswith("%"):
            text = text[:-1].strip()
        m = _HP_FRACTION_RE.match(text)
        if m:
            current, maximum = float(m.group(1)), float(m.group(2))
            return (current / maximum) * 100 if maximum else None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _turn_hp_snapshot(match_events):
    """turn -> {"player": {species_key: hp_percent}, "opponent":
    {species_key: hp_percent}}, reflecting known HP as of the START of that
    turn - every hp_change event bucketed under an EARLIER turn (same
    forward-assignment convention as _turn_faints: a field_state's `turn`
    sets the "current turn" for events that follow it) has already been
    applied, but the CURRENT turn's own hp_change events have not - the
    exact same "snapshot first, this turn's own outcomes inform the NEXT
    turn" ordering decision_windows.build_decision_windows() itself uses for
    fainted/known_moves/active (see that function's own Pass 2 comment).
    A species with no hp_change event yet (e.g. an untouched turn-1 lead,
    or any match with no hp_change data at all) simply has no entry here -
    "skip, don't guess" applies to a missing HP read exactly as much as
    anywhere else in this module. Keyed by `_species_key` (Mega/regional-form
    stripped), NOT the raw event species name, so a Mega-evolved Pokemon's
    later hp_change events still resolve against available_pokemon's base
    roster name (see `_species_key`'s own docstring for the real bug this
    avoids) - callers must look this up via `_species_key(sp)` too, never
    the raw species string."""
    turns_seen = sorted({t for t in (
        _normalize_turn(e.get("turn")) for e in match_events
        if str(e.get("event", "")).strip() == "field_state"
    ) if t is not None})
    if not turns_seen:
        return {}

    current_turn = None
    buckets = {t: {"player": [], "opponent": []} for t in turns_seen}
    for e in match_events:
        kind = str(e.get("event", "")).strip()
        if kind == "field_state":
            t = _normalize_turn(e.get("turn"))
            if t is not None:
                current_turn = t
            continue
        if kind != "hp_change" or current_turn is None:
            continue
        side = e.get("actor")
        if side not in _SIDES or not e.get("pokemon"):
            continue
        hp = _coerce_hp_percent(e.get("hp_percent"))
        if hp is None:
            continue
        buckets[current_turn][side].append((_species_key(e["pokemon"]), hp))

    snapshot_by_turn = {}
    running = {"player": {}, "opponent": {}}
    for t in turns_seen:
        snapshot_by_turn[t] = {"player": dict(running["player"]), "opponent": dict(running["opponent"])}
        for side in _SIDES:
            for species_key, hp in buckets[t][side]:
                running[side][species_key] = hp
    return snapshot_by_turn


def _speed_tool_name(detail):
    """"ability: Swift Swim" / "item: Choice Scarf" -> "Swift Swim" / "Choice
    Scarf" if it's one of the small, curated set of items/abilities that
    concretely grant a speed edge (see _SPEED_ITEMS/_SPEED_ABILITIES) - None
    for anything else (an ability/item reveal with nothing to do with speed,
    e.g. "ability: Intimidate"), so this never over-claims "speed control"
    from an unrelated reveal. Reads the "ability: X"/"item: X" convention
    showdown_import.py's -ability/-item handler produces (see its own
    docstring) - the OCR/video pipeline's item_or_ability_activated events
    don't reliably follow this exact prefix convention today, so this under-
    detects (never over-detects) on video-sourced matches, same honest
    limitation as this module's other source-asymmetric signals (e.g.
    designated_sweeper's actor-gated stat_change reads)."""
    text = str(detail or "").strip()
    m = re.match(r"^(ability|item):\s*(.+)$", text, re.IGNORECASE)
    if not m:
        return None
    name = m.group(2).strip()
    low = name.lower()
    if low in _SPEED_ITEMS or low in _SPEED_ABILITIES:
        return name
    return None


def _turn_speed_tools(match_events):
    """turn -> {"player": {(pokemon, tool_name), ...}, "opponent": {...}},
    cumulative as of the START of that turn - same "once revealed, stays
    known" running-accumulation convention as _turn_hp_snapshot (a Choice
    Scarf revealed on turn 2 stays a known factor for every later turn; it
    doesn't un-reveal itself). Only ever built from item_or_ability_activated
    events matching _speed_tool_name's curated list - an ability/item that
    never triggers a visible protocol message (e.g. Swift Swim that never
    actually procs because it never rains) is invisible here exactly like it
    would be to a coach without a Pokedex check, not guessed at."""
    turns_seen = sorted({t for t in (
        _normalize_turn(e.get("turn")) for e in match_events
        if str(e.get("event", "")).strip() == "field_state"
    ) if t is not None})
    if not turns_seen:
        return {}
    current_turn = None
    buckets = {t: {"player": [], "opponent": []} for t in turns_seen}
    for e in match_events:
        kind = str(e.get("event", "")).strip()
        if kind == "field_state":
            t = _normalize_turn(e.get("turn"))
            if t is not None:
                current_turn = t
            continue
        if kind != "item_or_ability_activated" or current_turn is None:
            continue
        side = e.get("actor")
        if side not in _SIDES or not e.get("pokemon"):
            continue
        tool = _speed_tool_name(e.get("detail"))
        if tool:
            buckets[current_turn][side].append((e["pokemon"], tool))

    snapshot_by_turn = {}
    running = {"player": set(), "opponent": set()}
    for t in turns_seen:
        snapshot_by_turn[t] = {"player": set(running["player"]), "opponent": set(running["opponent"])}
        for side in _SIDES:
            for item in buckets[t][side]:
                running[side].add(item)
    return snapshot_by_turn


def _trick_room_setters(match_events):
    """Which side(s) are known to have used the move "Trick Room" ANYWHERE in
    the match (straight from move_used events, whole-match - not a per-turn
    read) - used only to attribute WHO likely benefits from an active Trick
    Room (a team doesn't usually set up Trick Room unless it helps their own,
    presumably-slower side), never to claim which side is actually faster
    (base speeds aren't tracked - see module docstring's long-standing
    caveat on this, unchanged by this feature). Returns a subset of
    {"player", "opponent"} - empty if neither side's own Trick Room use was
    ever resolved to a side."""
    setters = set()
    for e in match_events:
        if str(e.get("event", "")).strip() != "move_used":
            continue
        side = e.get("actor")
        if side not in _SIDES:
            continue
        name = str(e.get("move") or e.get("detail") or "").strip()
        name = re.sub(r"\s*\(failed\)\s*$", "", name, flags=re.IGNORECASE).strip()
        if name.lower() == "trick room":
            setters.add(side)
    return setters


def _turn_stat_changes(match_events):
    """turn -> {"player": [(pokemon, stat, direction), ...], "opponent": [...]},
    bucketed by the LITERAL turn a stat_change event occurred in - same
    forward-assignment convention as _turn_faints. Used only by
    compute_momentum's "big stat boost achieved" category - a different,
    per-turn question from _designated_sweeper_candidates' own whole-match
    boost tally, which keeps its own separate bucketing for that reason."""
    out = {}
    current_turn = None
    for e in match_events:
        kind = str(e.get("event", "")).strip()
        if kind == "field_state":
            t = _normalize_turn(e.get("turn"))
            if t is not None:
                current_turn = t
            continue
        if kind != "stat_change" or current_turn is None:
            continue
        side = e.get("actor")
        if side not in _SIDES or not e.get("pokemon"):
            continue
        parsed = _parse_stat_change(e.get("detail"))
        if not parsed:
            continue
        stat, direction = parsed
        out.setdefault(current_turn, {"player": [], "opponent": []})[side].append((e["pokemon"], stat, direction))
    return out


def _screens_sides(screens_str):
    """"player Reflect, opponent Aurora Veil" -> {"player", "opponent"} - the
    set of sides with ANY screen active, parsed off field_state's own
    "screens" field convention (see adapters/pokemon/game.json's fields spec
    and showdown_import.py's _screens_value). "none"/empty -> empty set."""
    sides = set()
    for token in str(screens_str or "").split(","):
        token = token.strip()
        if token.startswith("player "):
            sides.add("player")
        elif token.startswith("opponent "):
            sides.add("opponent")
    return sides


def _turn_failed_moves(window):
    """{"player": [pokemon, ...], "opponent": [...]} - this turn's chosen
    moves whose recorded name carried the "(failed)" qualifier (see
    decision_windows._move_name's own docstring for where this convention
    comes from) - i.e. it was used but didn't connect (blocked by Protect,
    missed, etc.). Purely descriptive context for compute_momentum - per the
    manual's own explicit instruction, a failed move is NEVER auto-flagged as
    a mistake here, just surfaced as a fact for a human to interpret in
    context."""
    out = {"player": [], "opponent": []}
    for side in _SIDES:
        for act in window[side]["chosen_actions"]:
            if act.get("type") != "move":
                continue
            raw = act.get("move") or ""
            if re.search(r"\(failed\)\s*$", raw, re.IGNORECASE):
                out[side].append(act["pokemon"])
    return out


def compute_advantage_score(window, conditions=None, hp_snapshot=None):
    """One decision_windows.py window -> an int in [-SCORE_CLAMP, SCORE_CLAMP],
    positive favoring the player. See module docstring for exactly what is
    and isn't folded into this number. `conditions` is one entry of
    _turn_field_conditions()'s output (or None/{} if unavailable - the score
    just falls back to alive-count differential alone). `hp_snapshot` is one
    entry of _turn_hp_snapshot()'s output (or None/{} if unavailable)."""
    player_alive = len(window["player"]["available_pokemon"])
    opponent_alive = len(window["opponent"]["available_pokemon"])
    score = (player_alive - opponent_alive) * ALIVE_WEIGHT

    tailwind = (conditions or {}).get("tailwind")
    if tailwind == "player":
        score += TAILWIND_WEIGHT
    elif tailwind == "opponent":
        score -= TAILWIND_WEIGHT
    # "both"/"none"/None: no adjustment - either it benefits nobody in
    # particular or it simply wasn't reported this turn.

    hp_snapshot = hp_snapshot or {}
    player_hp_known = [v for v in (hp_snapshot.get("player", {}).get(_species_key(sp))
                                    for sp in window["player"]["available_pokemon"]) if v is not None]
    opponent_hp_known = [v for v in (hp_snapshot.get("opponent", {}).get(_species_key(sp))
                                      for sp in window["opponent"]["available_pokemon"]) if v is not None]
    # Only adjust when BOTH sides have at least one known HP value this turn -
    # a one-sided read (e.g. only the player's damage has ever been reported)
    # can't produce a meaningful differential, so it's skipped rather than
    # compared against an assumed 100% for the unknown side.
    if player_hp_known and opponent_hp_known:
        hp_diff = (sum(player_hp_known) / len(player_hp_known)) - (sum(opponent_hp_known) / len(opponent_hp_known))
        score += hp_diff * HP_WEIGHT

    return max(-SCORE_CLAMP, min(SCORE_CLAMP, round(score)))


def estimate_win_probability(score):
    """Squashes an advantage score into a bounded 0-100 number via tanh - a
    smooth, monotonic, always-defined transform, NOT a calibrated
    probability (see module docstring - this is the single most important
    caveat in this whole file). Deliberately never returns exactly 0 or 100,
    since this heuristic should never claim total certainty."""
    return round(50 + 50 * math.tanh(score / WIN_PROB_SOFTNESS), 1)


def _reasons_for_turn(prev_conditions, conditions, lost):
    """Plain-language notes explaining why THIS turn's score moved, built
    only from things that are concretely true this turn (a Pokemon that
    dropped out of `available_pokemon` since the previous turn's snapshot,
    a field condition that's newly active compared to the turn before) -
    never a speculative "because X was a bad move," which is exactly what
    flag_mistake_candidates keeps separate and conservative.

    `lost` is {"player": set(...), "opponent": set(...)} - species present
    in the PREVIOUS turn's available_pokemon but missing from this turn's.
    Deliberately keyed off the available_pokemon diff (the same list the
    score itself is computed from) rather than re-scanning raw
    pokemon_fainted events by their literal turn number: a faint that
    happens DURING turn N doesn't reduce the alive count until turn N+1's
    snapshot (decision_windows.py's own "reflects state as of the START of
    the turn" rule) - keying reasons off the same diff the score uses keeps
    a turn's reasons and its score change always talking about the same
    thing."""
    reasons = []
    for side in _SIDES:
        for mon in sorted(lost.get(side, ())):
            reasons.append(f"{_SIDE_LABEL[side]} lost {mon}")

    cond = conditions or {}
    prev = prev_conditions or {}
    tailwind = cond.get("tailwind")
    if tailwind in ("player", "opponent") and prev.get("tailwind") != tailwind:
        reasons.append(f"{_SIDE_LABEL[tailwind]} gained Tailwind")
    if cond.get("trick_room") and not prev.get("trick_room"):
        reasons.append("Trick Room is active")
    weather = cond.get("weather")
    if weather and weather != "none" and weather != prev.get("weather"):
        reasons.append(f"Weather: {weather}")
    terrain = cond.get("terrain")
    if terrain and terrain != "none" and terrain != prev.get("terrain"):
        reasons.append(f"Terrain: {terrain}")

    if not reasons:
        reasons.append("No notable change this turn")
    return reasons


def compute_speed_control(conditions, speed_tools, trick_room_setters):
    """VGC Battle Intelligence Manual report #1 - Speed Control Advantage:
    who controls move order right now, from the concrete things this project
    can actually see: Tailwind (field_state's own side-attributed field),
    Trick Room (active or not, plus WHO is known to have set it up - a
    reasonable "who benefits" proxy, see _trick_room_setters), and any
    already-revealed Choice Scarf/Booster Energy/known speed ability (see
    _speed_tool_name's curated list). Priority moves and "naturally faster
    from base stats" calls are NOT attempted - this project tracks no move-
    priority or base-stat data at all (see module docstring's long-standing
    caveat) - so this report can under-detect real speed control (e.g. a
    Pokemon that's simply faster with no tool revealed at all) but never
    fabricates a "faster" claim it can't back up.

    Tailwind and Trick Room are reported as FACTORS ONLY, never scored here -
    `score`/compute_advantage_score already owns Tailwind's scoring
    (TAILWIND_WEIGHT), and Trick Room has never been scored anywhere in this
    module (no base-speed data to say who it actually favors) - re-scoring
    either here would double-count what `score` already reflects. Only the
    revealed-speed-tool signal is new information, so it's the only thing
    that moves this report's OWN `score` (see compute_position_score for how
    that piece then gets folded into the composed Position Score).

    `conditions` is one entry of _turn_field_conditions()'s output (or None).
    `speed_tools` is one entry of _turn_speed_tools()'s output (or None).
    `trick_room_setters` is _trick_room_setters()'s whole-match set.

    Returns {"score": int in [-SPEED_SCORE_CLAMP, SPEED_SCORE_CLAMP]
    (positive favors player; tool-driven only), "side": "player"|"opponent"|
    "contested"|"none", "factors": [str, ...]}."""
    cond = conditions or {}
    tools = speed_tools or {"player": set(), "opponent": set()}
    score = 0
    factors = []

    tailwind = cond.get("tailwind")
    if tailwind == "player":
        factors.append("Player has Tailwind active (doubled team Speed)")
    elif tailwind == "opponent":
        factors.append("Opponent has Tailwind active (doubled team Speed)")
    elif tailwind == "both":
        factors.append("Both sides have Tailwind active - net Speed order unaffected")

    if cond.get("trick_room"):
        if trick_room_setters == {"player"}:
            factors.append("Trick Room is active (Player set it up - likely favors Player's slower attackers)")
        elif trick_room_setters == {"opponent"}:
            factors.append("Trick Room is active (Opponent set it up - likely favors Opponent's slower attackers)")
        else:
            factors.append("Trick Room is active (reverses Speed order - who it favors isn't determinable "
                            "from data tracked here)")

    for side in _SIDES:
        for pokemon, tool in sorted(tools.get(side, ())):
            delta = SPEED_TOOL_WEIGHT if side == "player" else -SPEED_TOOL_WEIGHT
            score += delta
            factors.append(f"{_SIDE_LABEL[side]}'s {pokemon} has revealed {tool}")

    score = max(-SPEED_SCORE_CLAMP, min(SPEED_SCORE_CLAMP, round(score)))
    if not factors:
        factors.append("No speed-control factors detected this turn")

    if score > 0:
        side_label = "player"
    elif score < 0:
        side_label = "opponent"
    elif tailwind == "both" or cond.get("trick_room"):
        side_label = "contested"
    else:
        side_label = "none"

    return {"score": score, "side": side_label, "factors": factors}


def _board_move_categories(known_moves_dict):
    """Given window[side]["known_moves"] (species -> revealed moves for the
    CURRENT board only - decision_windows.py's own per-turn snapshot), returns
    which curated danger-move categories are present: a subset of {"spread",
    "fake_out", "redirection"} - see _SPREAD_MOVES/_REDIRECTION_MOVES for the
    exact, small, curated move lists this checks against."""
    cats = set()
    for moves in known_moves_dict.values():
        for mv in moves:
            low = re.sub(r"\s*\(failed\)\s*$", "", str(mv or ""), flags=re.IGNORECASE).strip().lower()
            if low in _SPREAD_MOVES:
                cats.add("spread")
            elif low == "fake out":
                cats.add("fake_out")
            elif low in _REDIRECTION_MOVES:
                cats.add("redirection")
    return cats


_THREAT_TOOL_LABEL = {
    "spread": "a revealed spread move (can hit both opposing Pokemon at once)",
    "fake_out": "revealed Fake Out (priority flinch support)",
    "redirection": "a revealed redirection move (Follow Me/Rage Powder/Ally Switch)",
}


def compute_threat_pressure(window, faints_this_turn):
    """VGC Battle Intelligence Manual report #2 - Threat Pressure: the danger
    each side projects right now, from the concrete things this project can
    actually see: which curated danger-move categories the CURRENT board has
    already revealed (spread damage, Fake Out, redirection - see
    _board_move_categories), and how many KOs were actually scored this turn.
    KO potential in the "could this side one-shot something" sense is NOT
    attempted - this project has no damage-calc/base-stat/EV data at all, so
    claiming a specific KO threat would be a guess dressed up as a number
    (same discipline compute_advantage_score's own docstring already holds
    itself to for Trick Room/weather/terrain).

    This turn's actual KOs are reported as a FACTOR/count only, never
    scored here - a KO already changes `player_alive`/`opponent_alive` (and
    therefore `score`) as of the NEXT turn's snapshot (decision_windows.py's
    own "reflects state as of the START of the turn" rule), so scoring it a
    second time here would double-count what `score` already captures one
    turn later. Only the revealed-danger-move-category signal is new
    information, so it's the only thing that moves this report's OWN
    `score`.

    `window` is one decision_windows.build_decision_windows() entry (needs
    both sides' `known_moves`). `faints_this_turn` is one entry of
    _turn_faints()'s output (or None/{}).

    Returns {"score": int in [-THREAT_SCORE_CLAMP, THREAT_SCORE_CLAMP]
    (positive favors player; tool-driven only), "side": "player"|"opponent"|
    "even", "factors": [str, ...], "player_tools": [...], "opponent_tools":
    [...]}."""
    score = 0
    factors = []
    per_side_cats = {}
    for side in _SIDES:
        cats = _board_move_categories(window[side]["known_moves"])
        per_side_cats[side] = cats
        sign = 1 if side == "player" else -1
        for cat in sorted(cats):
            score += sign * THREAT_TOOL_WEIGHT
            factors.append(f"{_SIDE_LABEL[side]}'s board has {_THREAT_TOOL_LABEL[cat]}")

    faints = faints_this_turn or {}
    player_kos = len(faints.get("opponent", []))
    opponent_kos = len(faints.get("player", []))
    if player_kos:
        factors.append(f"Player scored {player_kos} KO{'s' if player_kos != 1 else ''} this turn")
    if opponent_kos:
        factors.append(f"Opponent scored {opponent_kos} KO{'s' if opponent_kos != 1 else ''} this turn")

    score = max(-THREAT_SCORE_CLAMP, min(THREAT_SCORE_CLAMP, round(score)))
    if not factors:
        factors.append("No notable threat-pressure factors this turn")

    if score > 0:
        side_label = "player"
    elif score < 0:
        side_label = "opponent"
    else:
        side_label = "even"

    return {
        "score": score, "side": side_label, "factors": factors,
        "player_tools": sorted(per_side_cats["player"]), "opponent_tools": sorted(per_side_cats["opponent"]),
    }


def compute_resource_advantage(window, conditions, hp_snapshot):
    """VGC Battle Intelligence Manual report #3 - Resource Advantage:
    "future options rather than immediate board power" - remaining
    Pokemon, known HP, and active screens. Sash/berry consumption,
    Intimidate availability, and weather/terrain-SETTER availability (i.e.
    "does this side still have an unrevealed Pokemon on the bench that could
    do this") are explicitly NOT modeled here - this project has no per-
    species item/ability dex at all (only whatever a real
    item_or_ability_activated event has already revealed - a fact about the
    PAST, not a "remaining resource" claim about the bench), so attempting
    "future options" for anything beyond alive-count/HP/screens would be a
    guess, not a report. This is a real, honest gap versus the manual's own
    fuller wish-list, not an oversight.

    Alive-Pokemon-count and known-HP use the exact SAME weights as
    `score`/compute_advantage_score (ALIVE_WEIGHT, HP_WEIGHT) - this report's
    `board_score` field is therefore intentionally a close descriptive
    mirror of what `score` already reflects (shown here for a self-contained
    per-report display), NOT a second number to add on top of `score` -
    compute_position_score only ever folds in this report's OWN
    `screen_score` field (the one genuinely NEW signal, not already present
    in `score`), never `board_score`, to avoid double-counting.

    Returns {"board_score", "screen_score", "score" (board_score +
    screen_score, clamped, for a single self-contained display number),
    "player_alive", "opponent_alive", "player_avg_hp", "opponent_avg_hp",
    "screens": {"player": bool, "opponent": bool}, "factors": [str, ...]}."""
    player_alive = len(window["player"]["available_pokemon"])
    opponent_alive = len(window["opponent"]["available_pokemon"])
    board_score = (player_alive - opponent_alive) * ALIVE_WEIGHT
    factors = [
        f"Player has {player_alive} Pokemon remaining",
        f"Opponent has {opponent_alive} Pokemon remaining",
    ]

    hp_snapshot = hp_snapshot or {}
    player_hp_known = [v for v in (hp_snapshot.get("player", {}).get(_species_key(sp))
                                    for sp in window["player"]["available_pokemon"]) if v is not None]
    opponent_hp_known = [v for v in (hp_snapshot.get("opponent", {}).get(_species_key(sp))
                                      for sp in window["opponent"]["available_pokemon"]) if v is not None]
    player_avg_hp = round(sum(player_hp_known) / len(player_hp_known), 1) if player_hp_known else None
    opponent_avg_hp = round(sum(opponent_hp_known) / len(opponent_hp_known), 1) if opponent_hp_known else None
    if player_avg_hp is not None:
        factors.append(f"Player's known Pokemon average {player_avg_hp}% HP")
    if opponent_avg_hp is not None:
        factors.append(f"Opponent's known Pokemon average {opponent_avg_hp}% HP")
    if player_hp_known and opponent_hp_known:
        board_score += (player_avg_hp - opponent_avg_hp) * HP_WEIGHT

    screens_up = _screens_sides((conditions or {}).get("screens"))
    screen_score = 0
    for side in _SIDES:
        if side in screens_up:
            screen_score += RESOURCE_SCREEN_WEIGHT if side == "player" else -RESOURCE_SCREEN_WEIGHT
            factors.append(f"{_SIDE_LABEL[side]} has a screen up (Reflect/Light Screen/Aurora Veil)")

    board_score = max(-RESOURCE_SCORE_CLAMP, min(RESOURCE_SCORE_CLAMP, round(board_score)))
    combined = max(-RESOURCE_SCORE_CLAMP, min(RESOURCE_SCORE_CLAMP, board_score + screen_score))

    return {
        "board_score": board_score, "screen_score": screen_score, "score": combined,
        "player_alive": player_alive, "opponent_alive": opponent_alive,
        "player_avg_hp": player_avg_hp, "opponent_avg_hp": opponent_avg_hp,
        "screens": {"player": "player" in screens_up, "opponent": "opponent" in screens_up},
        "factors": factors,
    }


def compute_momentum(delta, lost, stat_changes_this_turn, screens_gained, failed_moves):
    """VGC Battle Intelligence Manual report #4 - Momentum: "how much this
    turn improved or worsened position," built from concrete per-turn facts,
    categorized onto the manual's own explicit event list. `delta` is this
    turn's change in `score` (already computed by build_momentum_timeline) -
    Momentum doesn't invent a second number, it explains and categorizes the
    SAME swing `score`'s own delta already represents.

    `lost` is {"player": set(...), "opponent": set(...)} - species that
    dropped out of available_pokemon since the previous turn (the same input
    _reasons_for_turn already uses). `stat_changes_this_turn` is one entry of
    _turn_stat_changes()'s output (or None). `screens_gained` is
    {"player": bool, "opponent": bool} - a screen that's newly up this turn
    that wasn't up last turn. `failed_moves` is _turn_failed_moves()'s output
    for this turn.

    Per the manual's own explicit instruction, a failed/blocked move (e.g.
    "But it failed!", a Protect that got broken through) is NEVER auto-
    flagged as a mistake - it's surfaced as its own "context" category,
    distinct from "positive"/"negative", for a human to judge in context.

    Returns {"delta", "direction": "gained"|"lost"|"neutral", "events":
    [{"category": "positive"|"negative"|"context", "type": str, "side": str,
    "detail": str}, ...]}."""
    events = []
    for side in _SIDES:
        opp = "opponent" if side == "player" else "player"
        for mon in sorted(lost.get(side, ())):
            events.append({"category": "negative", "type": "own_pokemon_fainted", "side": side,
                           "detail": f"{_SIDE_LABEL[side]} lost {mon}"})
            events.append({"category": "positive", "type": "opponent_pokemon_fainted", "side": opp,
                           "detail": f"{_SIDE_LABEL[side]}'s {mon} fainted, a gain for {_SIDE_LABEL[opp]}"})

    for side in _SIDES:
        for pokemon, stat, direction in (stat_changes_this_turn or {}).get(side, []):
            if direction > 0 and stat in _OFFENSIVE_STATS:
                events.append({"category": "positive", "type": "big_stat_boost", "side": side,
                               "detail": f"{_SIDE_LABEL[side]}'s {pokemon}'s {stat} rose"})

    for side in _SIDES:
        if (screens_gained or {}).get(side):
            events.append({"category": "positive", "type": "screen_established", "side": side,
                           "detail": f"{_SIDE_LABEL[side]} set up a screen this turn"})

    for side in _SIDES:
        for pokemon in (failed_moves or {}).get(side, []):
            events.append({"category": "context", "type": "move_failed_or_blocked", "side": side,
                           "detail": f"{_SIDE_LABEL[side]}'s {pokemon} had a move fail or get blocked - "
                                     f"worth reviewing in context, not automatically a mistake"})

    if delta > MOMENTUM_NEUTRAL_BAND:
        direction = "gained"
    elif delta < -MOMENTUM_NEUTRAL_BAND:
        direction = "lost"
    else:
        direction = "neutral"

    return {"delta": delta, "direction": direction, "events": events}


def position_score_label(score):
    """Maps a Position-Score-scale number (the same [-100, 100] scale
    compute_advantage_score/`score` already uses) onto the VGC Battle
    Intelligence Manual's own named bands, verbatim: 80 to 100 Dominating,
    50 to 79 Strong Advantage, 20 to 49 Slight Advantage, -19 to 19 Even, -20
    to -49 Slight Disadvantage, -50 to -79 Major Disadvantage, -80 to -100
    Losing (see POSITION_SCORE_BANDS)."""
    s = max(-100, min(100, round(score)))
    for lo, hi, label in POSITION_SCORE_BANDS:
        if lo <= s <= hi:
            return label
    return "Even"  # unreachable - POSITION_SCORE_BANDS fully covers [-100, 100]


def compute_position_score(score, speed_control, threat_pressure, resource_advantage):
    """VGC Battle Intelligence Manual report #5 - Position Score: this
    project's master per-turn evaluation, composing the other reports the
    manual itself lists as Position Score's own inputs (Speed Control
    Advantage, Threat Pressure, Resource Advantage - Momentum is a per-turn
    DELTA of this same number, not one of its inputs, so it isn't folded in
    here - see compute_momentum).

    Rather than inventing a brand-new number that could silently drift out
    of sync with `score` (compute_advantage_score - already the alive-count/
    Tailwind/known-HP-based number every existing caller and test in this
    file relies on being stable), Position Score is `score` ITSELF, nudged by
    each sub-report's own SMALL, NEW, non-overlapping signal:
    speed_control's tool-only score, threat_pressure's danger-move-category-
    only score, and resource_advantage's screen-only score - see each of
    those functions' own docstrings for exactly why their OTHER fields
    (Tailwind, KOs-this-turn, alive-count/HP) are deliberately left out here:
    `score` already reflects them (Tailwind/alive-count/HP directly; KOs
    this-turn indirectly, one turn later, via decision_windows.py's own
    "reflects state as of the START of the turn" rule), so adding them again
    here would double-count.

    Returns {"value": int in [-100, 100], "label": str} - `label` is one of
    POSITION_SCORE_BANDS' own names."""
    value = score
    if speed_control:
        value += speed_control.get("score", 0)
    if threat_pressure:
        value += threat_pressure.get("score", 0)
    if resource_advantage:
        value += resource_advantage.get("screen_score", 0)
    value = max(-100, min(100, round(value)))
    return {"value": value, "label": position_score_label(value)}


_RISK_POSTURE_BY_LABEL = {
    "Dominating": ("safe", "Comfortably ahead - favor safe, low-variance lines that preserve the lead "
                           "rather than risking it for a faster win."),
    "Strong Advantage": ("safe", "Comfortably ahead - favor safe, low-variance lines that preserve the lead "
                                 "rather than risking it for a faster win."),
    "Slight Advantage": ("cautiously_safe", "Slightly ahead - lean toward safer lines, but a good high-value "
                                            "read is still reasonable."),
    "Even": ("balanced", "Roughly even - play the matchup on its own merits rather than leaning toward "
                         "either extreme."),
    "Slight Disadvantage": ("cautiously_aggressive", "Slightly behind - a solid read is worth the risk, "
                                                      "though not yet a must-gamble spot."),
    "Major Disadvantage": ("aggressive", "Clearly behind - a low-risk line likely still loses; an "
                                         "aggressive, higher-variance read is reasonable here."),
    "Losing": ("aggressive", "Clearly behind - a low-risk line likely still loses; an aggressive, "
                             "higher-variance read is reasonable here."),
}


def compute_risk_management(position_label):
    """VGC Battle Intelligence Manual report #6 - Risk Management: strategic
    posture derived purely from Position Score's own band (see
    position_score_label) - safe/low-variance lines when comfortably ahead,
    aggressive/higher-variance reads become reasonable when clearly behind,
    balanced in between. The manual itself only names 3 tiers (Ahead/Even/
    Behind); this project's Position Score has 7 bands, so the 2 "Slight"
    bands are interpolated sensibly between "safe" and "aggressive" rather
    than forced into one extreme or the other.

    This is intentionally the least "measured" of the six reports - it's
    coaching GUIDANCE about strategic posture, not a fact about what
    happened, so it's phrased as guidance/context, never as an assertion.
    Per the manual's explicit instruction (see compute_momentum), a failed/
    blocked move this turn is never treated as evidence the posture was
    wrong - context, not a penalty.

    Returns {"posture": str, "guidance": str}."""
    posture, guidance = _RISK_POSTURE_BY_LABEL.get(position_label, ("balanced",
        "Roughly even - play the matchup on its own merits rather than leaning toward either extreme."))
    return {"posture": posture, "guidance": guidance}


def build_momentum_timeline(events, match_number):
    """Returns one entry per turn (oldest first) for `match_number`:
    {"turn", "match", "player_alive", "opponent_alive", "score",
     "delta" (change from the previous turn's score, 0 for the first turn),
     "win_probability", "reasons": [str, ...],
     "speed_control", "threat_pressure", "resource_advantage", "momentum",
     "position_score", "risk_management"}

    The last 6 keys are the VGC Battle Intelligence Manual's own report
    framework (added 2026-07-09) - see compute_speed_control/
    compute_threat_pressure/compute_resource_advantage/compute_momentum/
    compute_position_score/compute_risk_management's own docstrings for what
    each one means and, critically, exactly which pieces of `score` they do
    and don't re-derive (to avoid double-counting - see
    compute_position_score's docstring in particular). These are ADDITIVE
    keys only - every field that existed before this feature (`score`,
    `delta`, `win_probability`, `reasons`, etc.) keeps its exact prior
    meaning and arithmetic; nothing about this module's pre-existing
    behavior changed to add them.

    Built directly on decision_windows.build_decision_windows() for the
    alive-Pokemon-count/board data (so it inherits that function's turn
    bucketing and its documented limitations - most notably: returns []
    for a match with no field_state/turn events at all)."""
    windows = build_decision_windows(events, match_number)
    if not windows:
        return []

    match_events = [e for e in events if e.get("match") == match_number]
    conditions_by_turn = _turn_field_conditions(match_events)
    hp_by_turn = _turn_hp_snapshot(match_events)
    faints_by_turn = _turn_faints(match_events)
    speed_tools_by_turn = _turn_speed_tools(match_events)
    stat_changes_by_turn = _turn_stat_changes(match_events)
    trick_room_setters = _trick_room_setters(match_events)

    timeline = []
    prev_score = None
    prev_conditions = None
    prev_available = None
    for w in windows:
        t = w["turn"]
        conditions = conditions_by_turn.get(t)
        score = compute_advantage_score(w, conditions, hp_by_turn.get(t))
        delta = 0 if prev_score is None else score - prev_score
        current_available = {side: set(w[side]["available_pokemon"]) for side in _SIDES}
        lost = ({side: (prev_available[side] - current_available[side]) for side in _SIDES}
                if prev_available is not None else {side: set() for side in _SIDES})

        faints_this_turn = faints_by_turn.get(t, {})
        speed_control = compute_speed_control(conditions, speed_tools_by_turn.get(t), trick_room_setters)
        threat_pressure = compute_threat_pressure(w, faints_this_turn)
        resource_advantage = compute_resource_advantage(w, conditions, hp_by_turn.get(t))
        position_score = compute_position_score(score, speed_control, threat_pressure, resource_advantage)
        risk_management = compute_risk_management(position_score["label"])

        prev_screens = _screens_sides((prev_conditions or {}).get("screens"))
        current_screens = _screens_sides((conditions or {}).get("screens"))
        screens_gained = {side: (side in current_screens and side not in prev_screens) for side in _SIDES}
        momentum = compute_momentum(delta, lost, stat_changes_by_turn.get(t), screens_gained, _turn_failed_moves(w))

        timeline.append({
            "turn": t,
            "match": match_number,
            "player_alive": len(w["player"]["available_pokemon"]),
            "opponent_alive": len(w["opponent"]["available_pokemon"]),
            "score": score,
            "delta": delta,
            "win_probability": estimate_win_probability(score),
            "reasons": _reasons_for_turn(prev_conditions, conditions, lost),
            "speed_control": speed_control,
            "threat_pressure": threat_pressure,
            "resource_advantage": resource_advantage,
            "momentum": momentum,
            "position_score": position_score,
            "risk_management": risk_management,
        })
        prev_score = score
        prev_conditions = conditions or prev_conditions
        prev_available = current_available
    return timeline


def summarize_resources(momentum_timeline):
    """Match-level rollup of the timeline's alive-count columns - the
    "resource tracking" piece of the spec, distilled to what's actually
    knowable here (alive-Pokemon counts; see module docstring for why HP
    isn't part of this). Returns None for an empty timeline (nothing to
    summarize) rather than fabricating zeros.

    Inherits decision_windows.py's "reflects state as of the START of the
    turn" rule (see its own docstring) - so `*_alive_final` is the alive
    count going INTO the match's last turn, not necessarily the count after
    it. A side that faints its last Pokemon and loses ON that final turn
    will still show 1 alive here, since that Pokemon was genuinely still
    alive at the moment the turn began; this is a real, correct reflection
    of "what was known going in," not a bug - matching_end/`winner` (from
    the match's own battle_end event, not this module) is the source of
    truth for the actual final outcome."""
    if not momentum_timeline:
        return None
    return {
        "turns_played": len(momentum_timeline),
        "player_alive_start": momentum_timeline[0]["player_alive"],
        "opponent_alive_start": momentum_timeline[0]["opponent_alive"],
        "player_alive_final": momentum_timeline[-1]["player_alive"],
        "opponent_alive_final": momentum_timeline[-1]["opponent_alive"],
        "final_win_probability": momentum_timeline[-1]["win_probability"],
    }


def flag_mistake_candidates(events, match_number):
    """Conservative, pattern-based candidates worth a human's review - see
    module docstring for exactly what is and isn't asserted here. Returns
    a list of {"turn", "match", "type", "side", "detail"} dicts, oldest
    first; empty list if nothing matched (the common case for a clean
    match, not an error)."""
    windows = build_decision_windows(events, match_number)
    if not windows:
        return []

    match_events = [e for e in events if e.get("match") == match_number]
    faints_by_turn = _turn_faints(match_events)
    timeline = build_momentum_timeline(events, match_number)

    flags = []
    for w in windows:
        t = w["turn"]
        faints_this_turn = faints_by_turn.get(t, {})
        for side in _SIDES:
            switched_in = {a["pokemon"] for a in w[side]["chosen_actions"] if a["type"] == "switch"}
            for mon in faints_this_turn.get(side, []):
                if mon in switched_in:
                    flags.append({
                        "turn": t, "match": match_number, "type": "blind_switch_koed",
                        "side": side,
                        "detail": f"{_SIDE_LABEL[side]} switched in {mon} and it fainted the same turn - "
                                  f"worth checking whether the incoming matchup was foreseeable.",
                    })

    for entry in timeline:
        if abs(entry["delta"]) >= SWING_THRESHOLD:
            favored = "player" if entry["delta"] > 0 else "opponent"
            against = "opponent" if favored == "player" else "player"
            flags.append({
                "turn": entry["turn"], "match": match_number, "type": "big_momentum_swing",
                "side": against,
                "detail": f"Turn {entry['turn']}: the advantage score swung {abs(entry['delta'])} points "
                          f"toward {_SIDE_LABEL[favored]} - worth reviewing what happened this turn "
                          f"(not necessarily a mistake - could be a good play paying off, or a fair trade).",
            })

    flags.sort(key=lambda f: f["turn"])
    return flags


def _designated_sweeper_candidates(match_events, windows):
    """A Pokemon that received SWEEPER_BOOST_THRESHOLD+ offensive stat boosts
    (Attack/Sp. Atk/Speed rising) over the course of the match - a likely
    designated win condition. Uses the SAME forward-turn-assignment
    convention as _turn_faints (a field_state's `turn` sets the "current
    turn" for events that follow it) to know which turn each boost
    happened on, purely for `turn_established` (the turn the threshold was
    first met) - not used for score/reason timing the way _turn_faints's
    literal-turn semantics are elsewhere in this module."""
    current_turn = None
    boost_turns = {"player": {}, "opponent": {}}
    for e in match_events:
        kind = str(e.get("event", "")).strip()
        if kind == "field_state":
            t = _normalize_turn(e.get("turn"))
            if t is not None:
                current_turn = t
            continue
        if kind != "stat_change" or current_turn is None:
            continue
        side = e.get("actor")
        if side not in _SIDES or not e.get("pokemon"):
            continue
        parsed = _parse_stat_change(e.get("detail"))
        if not parsed:
            continue
        stat, direction = parsed
        if stat not in _OFFENSIVE_STATS or direction <= 0:
            continue
        boost_turns[side].setdefault(e["pokemon"], []).append(current_turn)

    final_alive = ({side: set(windows[-1][side]["available_pokemon"]) for side in _SIDES}
                   if windows else {side: set() for side in _SIDES})

    candidates = []
    for side in _SIDES:
        for pokemon, turns in boost_turns[side].items():
            if len(turns) < SWEEPER_BOOST_THRESHOLD:
                continue
            survived = pokemon in final_alive[side]
            candidates.append({
                "type": "designated_sweeper", "side": side, "pokemon": pokemon,
                "turn_established": sorted(turns)[SWEEPER_BOOST_THRESHOLD - 1],
                "boost_count": len(turns),
                "survived_to_last_turn_seen": survived,
                "detail": (
                    f"{_SIDE_LABEL[side]}'s {pokemon} received {len(turns)} offensive stat boosts "
                    f"(Attack/Sp. Atk/Speed) over the match - a likely designated win condition"
                    + (", and was still alive as of the last turn seen."
                       if survived else ", though it didn't survive to the last turn seen.")
                ),
            })
    candidates.sort(key=lambda c: c["turn_established"])
    return candidates


def _primary_closer_candidates(windows, faints_by_turn):
    """The Pokemon on a side that most often had a move recorded on a turn
    the OPPOSING side lost a Pokemon - NOT proof its move caused the KO
    (doubles has 2 actions per side per turn, and a faint can come from
    residual/status damage rather than that turn's move), just a
    correlation worth a glance, same conservative spirit as
    big_momentum_swing. Needs CLOSER_COUNT_THRESHOLD+ such turns before
    flagging anything - a single coincidence proves nothing."""
    counts = {"player": Counter(), "opponent": Counter()}
    for w in windows:
        t = w["turn"]
        faints_this_turn = faints_by_turn.get(t, {})
        for side in _SIDES:
            opp_side = "opponent" if side == "player" else "player"
            if not faints_this_turn.get(opp_side):
                continue
            for act in w[side]["chosen_actions"]:
                if act["type"] == "move":
                    counts[side][act["pokemon"]] += 1

    candidates = []
    for side in _SIDES:
        if not counts[side]:
            continue
        pokemon, n = counts[side].most_common(1)[0]
        if n < CLOSER_COUNT_THRESHOLD:
            continue
        candidates.append({
            "type": "primary_closer", "side": side, "pokemon": pokemon, "count": n,
            "detail": (
                f"{_SIDE_LABEL[side]}'s {pokemon} acted on {n} of the turns an opposing Pokemon "
                f"fainted - a recurring closer, worth noting even though this doesn't prove ITS "
                f"move caused the KO (multiple actions can happen the same turn in doubles)."
            ),
        })
    return candidates


def infer_win_condition_candidates(events, match_number):
    """Returns a list of candidate dicts (see module docstring for the two
    patterns: `designated_sweeper`, `primary_closer`) - conservative,
    "worth a human's review," never an assertion of the actual game plan.
    Empty list is the common, valid case (most matches don't have a clean
    stat-boost sweep or a single standout closer). Returns [] for a match
    with no field_state/turn events at all, same as every other function
    in this module built on decision_windows.build_decision_windows()."""
    windows = build_decision_windows(events, match_number)
    if not windows:
        return []
    match_events = [e for e in events if e.get("match") == match_number]
    faints_by_turn = _turn_faints(match_events)
    sweepers = _designated_sweeper_candidates(match_events, windows)
    closers = _primary_closer_candidates(windows, faints_by_turn)
    return sweepers + closers


def _cumulative_known_moves(windows, side):
    """Union of every species' revealed moves seen on ANY turn's snapshot for
    `side`, in first-seen order. decision_windows.py's own known_moves is
    keyed per-turn to whichever Pokemon are currently on the BOARD that turn
    (see its _side_snapshot) - a Pokemon that already fainted and left the
    board drops out of later turns' known_moves dicts even though its
    earlier-revealed moves are still real, known information. This just
    re-assembles the full history a coach would actually remember, kept as
    its own local copy rather than reaching into decision_windows.py's
    private per-turn dict directly (same discipline as this module's other
    small local copies, e.g. _turn_faints)."""
    out = {}
    for w in windows:
        for sp, moves in w[side]["known_moves"].items():
            lst = out.setdefault(sp, [])
            for m in moves:
                if m not in lst:
                    lst.append(m)
    return out


def identify_threats(events, match_number):
    """Ranks the OPPONENT's revealed Pokemon by how much of a type-chart
    danger each one poses to the PLAYER's own brought roster - see module
    docstring for the full honest-scope caveat (species-typing only, no
    move-type data exists in this project). Unresolved species (not in
    pokedex.SPECIES_TYPES, on either side) are skipped - "skip, don't
    guess," the same rule backend/type_synergy.py's team_risk() holds
    itself to.

    Returns a list of {"pokemon", "side": "opponent", "threatens": [player
    species...], "threat_score", "known_moves_seen": [...]}, most-
    threatening first (ties broken alphabetically for determinism). Empty
    list if the match has no field_state/turn events, or if nothing on
    either side resolves against the type chart."""
    windows = build_decision_windows(events, match_number)
    if not windows:
        return []

    player_roster = set()
    opponent_roster = set()
    for w in windows:
        player_roster.update(w["player"]["available_pokemon"])
        opponent_roster.update(w["opponent"]["available_pokemon"])

    player_types = {sp: pokedex.SPECIES_TYPES[sp] for sp in player_roster if sp in pokedex.SPECIES_TYPES}
    if not player_types:
        return []

    known_moves = _cumulative_known_moves(windows, "opponent")

    threats = []
    for sp in opponent_roster:
        opp_types = pokedex.SPECIES_TYPES.get(sp)
        if not opp_types:
            continue
        threatens = []
        quad = 0
        for player_sp, p_types in player_types.items():
            best = max(pokedex.type_multiplier(atk, p_types) for atk in opp_types)
            if best > 1:
                threatens.append(player_sp)
                if best >= 4:
                    quad += 1
        if not threatens:
            continue
        threats.append({
            "pokemon": sp,
            "side": "opponent",
            "threatens": sorted(threatens),
            "threat_score": round(len(threatens) + 0.5 * quad, 2),
            "known_moves_seen": known_moves.get(sp, []),
        })

    threats.sort(key=lambda t: (-t["threat_score"], t["pokemon"]))
    return threats


def _match_winner(match_events):
    """"player"|"opponent"|None from this match's own `battle_end` event
    (see analyze_matches.py's read_winner()/showdown_import.py's
    build_battle_end_event() - both sources emit this the same way: `actor`
    and a `winner` field, either set to "player"/"opponent"/"unknown").
    None if there's no battle_end event at all, OR its winner is "unknown"
    (a tie/undetermined match) - "flag, don't guess" applies to the loss-
    attribution entry point built on this just as much as anywhere else in
    this module."""
    for e in match_events:
        if str(e.get("event", "")).strip() == "battle_end":
            w = e.get("winner") or e.get("actor")
            return w if w in _SIDES else None
    return None


def trace_loss_to_turn(events, match_number):
    """See module docstring for the full design rationale. Returns None if
    there's no field_state/turn data, or no definite winner/loser (see
    _match_winner). Otherwise returns {"loser", "winner", "decisive_turn"
    (int or None), "final_blow" ({"turn", "pokemon": [...]} or None),
    "detail"}."""
    match_events = [e for e in events if e.get("match") == match_number]
    winner = _match_winner(match_events)
    if winner is None:
        return None

    timeline = build_momentum_timeline(events, match_number)
    if not timeline:
        return None
    loser = "opponent" if winner == "player" else "player"

    def _loser_deficit(entry):
        loser_alive = entry["player_alive"] if loser == "player" else entry["opponent_alive"]
        winner_alive = entry["opponent_alive"] if loser == "player" else entry["player_alive"]
        return loser_alive - winner_alive

    deficits = [_loser_deficit(t) for t in timeline]
    # The LAST index with deficit >= 0 is, by construction, never followed by
    # another such index - so "never recovered after this point" is always
    # true of whichever turn this lands on. That only leaves two genuinely
    # unclear cases, handled explicitly below: never tied/ahead at all, or
    # tied/ahead all the way through the last turn recorded.
    last_even_or_ahead = max((i for i, d in enumerate(deficits) if d >= 0), default=None)

    decisive_turn = None
    if last_even_or_ahead is None:
        detail = (f"{_SIDE_LABEL[loser]} was already behind on alive-Pokemon count as of the "
                   f"earliest turn recorded - too early to pin the loss to a specific turn.")
    elif last_even_or_ahead == len(timeline) - 1:
        detail = f"{_SIDE_LABEL[loser]} was tied or ahead through the last turn recorded - no clear turn to blame."
    else:
        decisive_turn = timeline[last_even_or_ahead]["turn"]
        detail = (f"{_SIDE_LABEL[loser]} was last tied or ahead on turn {decisive_turn} - the deficit that "
                   f"opened up after that turn was never recovered, worth reviewing what happened there.")

    match_events_faints = _turn_faints(match_events)
    final_blow = None
    for t in sorted(match_events_faints.keys(), reverse=True):
        lost_mons = match_events_faints[t].get(loser, [])
        if lost_mons:
            final_blow = {"turn": t, "pokemon": list(lost_mons)}
            break

    return {
        "loser": loser,
        "winner": winner,
        "decisive_turn": decisive_turn,
        "final_blow": final_blow,
        "detail": detail,
    }


def analyze_match(events, match_number):
    """The one-call-per-match convenience entry point: everything this
    module can say about a single match, bundled together."""
    timeline = build_momentum_timeline(events, match_number)
    return {
        "match": match_number,
        "momentum_timeline": timeline,
        "resource_summary": summarize_resources(timeline),
        "mistake_candidates": flag_mistake_candidates(events, match_number),
        "win_condition_candidates": infer_win_condition_candidates(events, match_number),
        "threats": identify_threats(events, match_number),
        "loss_analysis": trace_loss_to_turn(events, match_number),
    }


def analyze_job(events):
    """Same "every match in one events.json, flattened, each match number
    stamped" convention as decision_windows.build_decision_windows_for_job -
    the entry point a backend endpoint calls. Returns a list of
    analyze_match()'s dicts, one per match, sorted by match number.

    Each match is analyzed inside its own try/except (added 2026-07-09,
    alongside the _normalize_turn/_coerce_hp_percent fixes above): a real,
    messy 30-match video job (job 303d13ba0940) surfaced two crashes here
    that were specific to individual matches' own messy raw data (a mixed
    int/str `turn` field on 2 matches, a non-numeric `hp_percent` string on a
    3rd) - both are now fixed at the source, but this module analyzes raw,
    AI/OCR-extracted event data that can still surprise it in some other way
    on some future job. Without this, one bad match used to take down the
    ENTIRE job's analysis (every other, perfectly fine match included) with
    it. A match that still fails for some new reason now gets a small
    `{"match": m, "error": str}` placeholder instead - "flag, don't crash,
    don't guess" applied one level up, matching this module's own long-
    standing discipline for uncertain per-turn data."""
    groups = group_by_match(events)
    out = []
    for m in sorted(groups.keys()):
        stamped = [e if e.get("match") == m else {**e, "match": m} for e in groups[m]]
        try:
            out.append(analyze_match(stamped, m))
        except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
            out.append({
                "match": m,
                "error": f"{type(exc).__name__}: {exc}",
                "momentum_timeline": [],
                "resource_summary": None,
                "mistake_candidates": [],
                "win_condition_candidates": [],
                "threats": [],
                "loss_analysis": None,
            })
    return out


_ALL_RISK_POSTURES = ("safe", "cautiously_safe", "balanced", "cautiously_aggressive", "aggressive")


def compute_job_battle_profile(job_results):
    """Aggregates analyze_job()'s per-match, per-turn six-report battle-
    intelligence data (tasks #220-226) into a single job-wide profile of the
    player's own skill set (tasks #234-237, added 2026-07-09, directly
    answering the user's "we want to get an overall analysis of their skill
    set" request once turn-by-turn intel across the whole job stopped
    crashing - see analyze_job's own docstring and ARCHITECTURE_HANDOFF.md).

    This is deliberately NOT a re-derivation of two things that already
    exist:
      - skill_scores.py's tempo/adaptability/execution/closing/overall
        scores - a separate, coarser heuristic computed directly from raw
        events, already exposed per-job via GET /jobs/{id}/skill-scores.
      - coach_report.py's win/loss record and report - already exposed via
        GET /jobs/{id}/record and /report.
    Everything below is instead a straightforward rollup of the six per-turn
    reports analyze_job() already computes (speed_control, threat_pressure,
    resource_advantage, momentum, position_score, risk_management) - no new
    heuristic scoring happens here, only counting/averaging what's already
    there. This gives turn-level texture the whole-match views above don't
    capture on their own (e.g. "what % of turns was speed control actually in
    the player's favor," not just "how good was their overall tempo").

    Win-condition and loss-pattern rollups are reported from the PLAYER's own
    side only (this is a profile of the player's OWN skill set, not the
    opponent's) - see win_condition_candidates'/loss_analysis' own docstrings
    for what "side"/"loser" mean there.

    speed_control's specific revealed tools (Choice Scarf, etc.) are NOT
    tallied here - unlike threat_pressure's player_tools/opponent_tools
    (structured category lists), speed_control only exposes them as freeform
    text in `factors` (e.g. "Regieleki revealed Choice Scarf") - parsing that
    back out would be re-deriving structured data from prose, the same
    guess-dressed-as-a-number trap this whole module's docstring warns
    against elsewhere. Only the `side` distribution (already structured) is
    rolled up for that report.

    Matches that failed to analyze (an `{"error": ...}` placeholder - see
    analyze_job) contribute no turns to any of these rollups and are counted
    separately via `matches_errored`, never silently dropped or silently
    treated as if they succeeded.

    Returns None if job_results is empty or no successfully-analyzed match
    has any turns recorded."""
    valid = [m for m in job_results if not m.get("error")]
    errored = [m for m in job_results if m.get("error")]
    all_turns = [t for m in valid for t in (m.get("momentum_timeline") or [])]
    if not all_turns:
        return None

    n_turns = len(all_turns)

    def _pct(count):
        return round(100 * count / n_turns, 1)

    # --- Position Score ---
    position_values = [t["position_score"]["value"] for t in all_turns]
    band_counts = Counter(t["position_score"]["label"] for t in all_turns)
    band_distribution = {label: _pct(band_counts.get(label, 0)) for _, _, label in POSITION_SCORE_BANDS}
    final_turn_values = [
        m["momentum_timeline"][-1]["position_score"]["value"]
        for m in valid if m.get("momentum_timeline")
    ]
    position_score = {
        "average": round(sum(position_values) / n_turns, 1),
        "worst": min(position_values),
        "best": max(position_values),
        "final_turn_average": (
            round(sum(final_turn_values) / len(final_turn_values), 1) if final_turn_values else None
        ),
        "band_distribution": band_distribution,
    }

    # --- Speed Control (side distribution only - see docstring) ---
    speed_sides = Counter(t["speed_control"]["side"] for t in all_turns)
    speed_control = {
        "player_favorable_pct": _pct(speed_sides.get("player", 0)),
        "opponent_favorable_pct": _pct(speed_sides.get("opponent", 0)),
        "contested_pct": _pct(speed_sides.get("contested", 0)),
        "none_pct": _pct(speed_sides.get("none", 0)),
    }

    # --- Threat Pressure ---
    threat_sides = Counter(t["threat_pressure"]["side"] for t in all_turns)
    player_tool_counts = Counter()
    opponent_tool_counts = Counter()
    for t in all_turns:
        player_tool_counts.update(t["threat_pressure"].get("player_tools", []))
        opponent_tool_counts.update(t["threat_pressure"].get("opponent_tools", []))
    threat_pressure = {
        "player_favorable_pct": _pct(threat_sides.get("player", 0)),
        "opponent_favorable_pct": _pct(threat_sides.get("opponent", 0)),
        "even_pct": _pct(threat_sides.get("even", 0)),
        "player_tool_counts": dict(player_tool_counts),
        "opponent_tool_counts": dict(opponent_tool_counts),
    }

    # --- Resource Advantage (screens only - see compute_resource_advantage's
    # own docstring for why board_score is never rolled up here either) ---
    player_screen_turns = sum(1 for t in all_turns if t["resource_advantage"]["screens"]["player"])
    opponent_screen_turns = sum(1 for t in all_turns if t["resource_advantage"]["screens"]["opponent"])
    resource_advantage = {
        "player_screen_uptime_pct": _pct(player_screen_turns),
        "opponent_screen_uptime_pct": _pct(opponent_screen_turns),
        "average_screen_score": round(sum(t["resource_advantage"]["screen_score"] for t in all_turns) / n_turns, 1),
    }

    # --- Momentum ---
    direction_counts = Counter(t["momentum"]["direction"] for t in all_turns)
    momentum_event_counts = Counter()
    for t in all_turns:
        for ev in t["momentum"].get("events", []):
            momentum_event_counts[ev["type"]] += 1
    momentum = {
        "gained_pct": _pct(direction_counts.get("gained", 0)),
        "lost_pct": _pct(direction_counts.get("lost", 0)),
        "neutral_pct": _pct(direction_counts.get("neutral", 0)),
        "event_counts": dict(momentum_event_counts),
    }

    # --- Risk Management (every posture key present, even at 0%, so the
    # frontend can render a stable set of bars/labels without special-casing
    # a missing key) ---
    posture_counts = Counter(t["risk_management"]["posture"] for t in all_turns)
    risk_management = {posture: _pct(posture_counts.get(posture, 0)) for posture in _ALL_RISK_POSTURES}

    # --- Mistake patterns (across all valid matches, not just this turn) ---
    all_mistakes = [f for m in valid for f in (m.get("mistake_candidates") or [])]
    mistake_patterns = {
        "counts_by_type": dict(Counter(f["type"] for f in all_mistakes)),
        "matches_with_any_mistake": sum(1 for m in valid if m.get("mistake_candidates")),
    }

    # --- Win-condition patterns (player's own side only - see docstring) ---
    all_candidates = [c for m in valid for c in (m.get("win_condition_candidates") or [])]
    sweeper_counts = Counter(
        c["pokemon"] for c in all_candidates
        if c["type"] == "designated_sweeper" and c["side"] == "player"
    )
    closer_counts = Counter(
        c["pokemon"] for c in all_candidates
        if c["type"] == "primary_closer" and c["side"] == "player"
    )
    win_condition_patterns = {
        "top_designated_sweepers": [
            {"pokemon": p, "times_established": n} for p, n in sweeper_counts.most_common(5)
        ],
        "top_primary_closers": [
            {"pokemon": p, "times_established": n} for p, n in closer_counts.most_common(5)
        ],
    }

    # --- Loss patterns (matches the PLAYER lost only - see docstring) ---
    player_losses = [
        m["loss_analysis"] for m in valid
        if m.get("loss_analysis") and m["loss_analysis"]["loser"] == "player"
    ]
    decisive_turns = [l["decisive_turn"] for l in player_losses if l["decisive_turn"] is not None]
    final_blow_counts = Counter(
        p for l in player_losses if l.get("final_blow") for p in l["final_blow"]["pokemon"]
    )
    loss_patterns = {
        "losses_analyzed": len(player_losses),
        "average_decisive_turn": (
            round(sum(decisive_turns) / len(decisive_turns), 1) if decisive_turns else None
        ),
        "common_final_blow_pokemon": [
            {"pokemon": p, "count": n} for p, n in final_blow_counts.most_common(5)
        ],
    }

    return {
        "matches_analyzed": len(valid),
        "matches_errored": len(errored),
        "turns_analyzed": n_turns,
        "position_score": position_score,
        "speed_control": speed_control,
        "threat_pressure": threat_pressure,
        "resource_advantage": resource_advantage,
        "momentum": momentum,
        "risk_management": risk_management,
        "mistake_patterns": mistake_patterns,
        "win_condition_patterns": win_condition_patterns,
        "loss_patterns": loss_patterns,
    }
