"""
decision_windows.py - for every turn of a match, reconstructs (a) what each
side had AVAILABLE at the moment it acted, and (b) what it actually CHOSE to
do. This is the raw material a future strategic-analysis layer (win
probability, momentum, mistake-candidate flagging - the wider architecture
spec's stage 11) will need to ask questions like "why Recover instead of
Protect" or "was there a better switch available here" - built now, on its
own, per an explicit user request to prioritize this specific piece ahead of
the larger engine.

Deliberately does NOT invent information a real coach wouldn't have had at
that moment:
  - "available moves" (`known_moves` below) means moves THIS Pokemon has
    already revealed earlier in THIS SAME MATCH - never its true, hidden
    four-move set. VGC teams keep that private; a coach (and this tool)
    only ever gets to see what's actually been used. A Pokemon that hasn't
    used anything yet has an empty known_moves list, not a guess. This is
    the same "never coach with information unavailable at that point"
    principle the wider spec calls "information state," applied at the
    turn level.
  - "switch_options" means the side's team-preview "brought" (pick-4)
    roster, minus anything that's fainted and minus whatever's already
    active - never the full 6-Pokemon team, since only the brought 4 are
    legal to switch to.

Honest scope/limitations, stated plainly (same standard the rest of this
project holds itself to):
  - Turn boundaries come ONLY from field_state events' own `turn` field
    (see adapters/pokemon/game.json's fields spec) - the one place turn
    number is actually read off the video. A match with zero field_state
    events has nothing to key turns off and returns an empty list rather
    than fabricating turn numbers - this is currently true of EVERY
    Showdown-imported match (showdown_import.py doesn't emit turn/
    field_state events at all, despite the raw protocol having an exact
    `|turn|N|` line that could resolve this - a real, worthwhile follow-up,
    not done here since it's a separate module).
  - A real, useful side-finding from building this: no code path in this
    project actually populates a structured `move` field on a real
    move_used event today. battle_text_parser.py's _event() (the OCR
    tier's own event builder) and every Gemini-vision-derived event both
    put the move name in `detail` instead (see battleTimeline.js's
    captionFor(), which already relies on this same fact for its move_used
    caption). accuracy_addons/moveset_validator.py's flag_implausible_moves
    expects a `move` field specifically and, as a direct consequence, has
    never actually matched a real event - a second, more fundamental
    reason (beyond the documented 15-species learnset-coverage gap) that
    check has found nothing on real jobs. _move_name() below works around
    this pragmatically by preferring `move` when present (future-proof)
    and falling back to `detail` (what's actually there today), stripping
    the " (failed)" qualifier battle_text_parser.py's failed-move variant
    appends - the move was still attempted/revealed even if it didn't
    connect, which is what "known_moves" is tracking.
  - A switch's target slot (which of the 2 active Pokemon it replaces)
    isn't tracked - active-list handling is best-effort capped at 2,
    dropping an already-fainted Pokemon first if a 3rd genuinely shows up,
    the exact same rule frontend/src/lib/battleTimeline.js's pushActive()
    already uses for its own state reconstruction.

Pure functions, no video/Gemini/network - safe to import from the backend
without pulling in analyze_matches.py's heavier dependencies (gemini_batch,
frame_dedup, etc.), the same reason skill_scores.py/type_synergy.py/
career.py don't import analyze_matches.py either.
"""

import re

from coach_report import group_by_match, ts

_FAILED_SUFFIX = re.compile(r"\s*\(failed\)\s*$", re.IGNORECASE)
_REGION_WORDS = r"(?:alolan|alola|galarian|galar|hisuian|hisui|paldean|paldea)"


def _species_key(name):
    """Normalized species key with Mega/regional-form annotations stripped -
    a Pokemon doesn't stop being the same team member because it Mega
    Evolved or is shown in a regional form (Species Clause: "Mega Evolution
    is a transformation of an existing team member, not a second Pokemon" -
    see adapters/pokemon/doubles.json's own rules note). Used ONLY to decide
    whether a `pokemon_fainted` event's species refers to the SAME roster
    entry as a team-preview/brought name written differently - never for a
    legality opinion (unlike analyze_matches._species_base_norm, which this
    intentionally does NOT import - see module docstring for why - this
    doesn't need that function's ALLOWED_SPECIES prefix-matching fallback,
    since both names being compared already came from this project's own
    events, not from an unconstrained AI/OCR read).

    A real bug this fixes: showdown_import.py's pokemon_fainted event
    reports a Mega-evolved Pokemon's POST-Mega name (e.g. "Charizard" that
    Mega Evolved reports as "Charizard-Mega-Y" when it later faints), which
    never matched the team-preview roster's base name under plain string
    comparison - so a Mega'd Pokemon that fainted was permanently
    miscounted as still alive in `available_pokemon`/`switch_options` for
    the rest of the match. Confirmed against a real, public replay
    (Geordivgc vs. JarlomenVGC) while building strategic_analysis.py
    (2026-07-04), which is what surfaced this."""
    n = re.sub(r"\(.*?\)", "", str(name or ""))                # "Mawile (Mega)" -> "Mawile "
    n = re.sub(r"(?i)^mega\s+", "", n)                          # "Mega Mawile" -> "Mawile"
    n = re.sub(r"(?i)[\s\-]mega[\s\-][xy]$", "", n)             # "Charizard-Mega-Y" -> "Charizard"
    n = re.sub(r"(?i)[\s\-]mega$", "", n)                       # "Mawile-Mega" -> "Mawile"
    n = re.sub(rf"(?i)^{_REGION_WORDS}\s+", "", n)              # "Alolan Ninetales" -> "Ninetales"
    n = re.sub(rf"(?i)[\s\-]{_REGION_WORDS}$", "", n)           # "Ninetales-Alola" -> "Ninetales"
    return re.sub(r"[^a-z0-9]", "", n.lower())


_TURN_STRING_RE = re.compile(r"^\s*-?\d+\s*$")


def _normalize_turn(raw):
    """Coerces a raw event's `turn` field into a comparable int, or None if it
    can't be read as one - the single choke point every turn-keyed helper in
    this module (and strategic_analysis.py, which imports this) reads a raw
    `turn` value through, so a match with a messy read degrades gracefully
    instead of crashing.

    A real bug this fixes: job 303d13ba0940's `turn` field - straight from
    the video/vision extraction pipeline, not hand-authored - comes back as a
    plain int on most events, but as a numeric STRING ("1" instead of 1, seen
    on match 14) or the literal string "unknown" (match 16 - the vision
    model's own admission it couldn't read the turn counter that moment) on
    others. Mixing int and str turn values in the same match crashes any
    sort()/set() built directly from the raw field ("'<' not supported
    between instances of 'str' and 'int'") - build_decision_windows' own
    `order.sort()` and several of strategic_analysis.py's per-turn bucketing
    helpers (_turn_hp_snapshot, _turn_speed_tools) all hit this on real
    footage before this existed. A numeric string is salvageable without
    guessing (it's exactly one int, just spelled as text); "unknown" and
    anything else non-numeric is treated exactly like a missing `turn` field
    already was - None, "we don't know," never a guess."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw) if raw.is_integer() else None
    if isinstance(raw, str) and _TURN_STRING_RE.match(raw):
        return int(raw)
    return None


def _names_of(value):
    """Same tolerant parsing as analyze_matches.py's names_of() / frontend/
    src/lib/battleTimeline.js's namesOf() - a Pokemon-name-bearing field can
    come back as a comma string, a list of strings, or a list of {"name"|
    "pokemon"|"species": ...} dicts. Kept as its own local copy rather than
    importing analyze_matches.py directly - see module docstring."""
    if value is None:
        return []
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    if isinstance(value, dict):
        n = value.get("name") or value.get("pokemon") or value.get("species")
        return [str(n).strip()] if n else []
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict):
                n = item.get("name") or item.get("pokemon") or item.get("species")
                if n:
                    out.append(str(n).strip())
        return out
    return []


def _move_name(e):
    """Best-effort move name for a move_used event - see module docstring's
    "no code path populates `move`" finding. Prefers a structured `move`
    field if one's ever present, else falls back to `detail` (what's
    actually there in every real event today), stripping the trailing
    " (failed)" qualifier so a failed move still counts as revealed."""
    name = e.get("move") or e.get("detail")
    if not name:
        return None
    cleaned = _FAILED_SUFFIX.sub("", str(name)).strip()
    return cleaned or None


def _cap_active(active, fainted, side):
    """Doubles caps active Pokemon at 2 per side - if a 3rd genuinely shows
    up (a switch recorded without ever seeing the corresponding faint/return
    of one of the current two), drop an already-fainted one first rather
    than an alive one, same rule as battleTimeline.js's pushActive()."""
    lst = active[side]
    while len(lst) > 2:
        drop = next((sp for sp in lst if sp in fainted[side]), lst[0])
        lst.remove(drop)


def _side_snapshot(side, active, fainted, known_moves, brought, actions_this_turn):
    roster = brought.get(side) or []
    fainted_keys = {_species_key(f) for f in fainted[side]}
    alive = [sp for sp in roster if _species_key(sp) not in fainted_keys]
    board = list(active[side])
    switch_options = [sp for sp in alive if sp not in board]
    chosen = [a for a in actions_this_turn if a["type"] in ("move", "switch")]
    return {
        "board": board,
        "available_pokemon": alive,
        "switch_options": switch_options,
        "known_moves": {sp: list(known_moves[side].get(sp, [])) for sp in board},
        "chosen_actions": chosen,
    }


def build_decision_windows(events, match_number):
    """Returns one window per turn for `match_number`, oldest first:
    {"turn": int, "match": match_number, "player": {...}, "opponent": {...}}
    where each side's dict is _side_snapshot()'s shape (board/
    available_pokemon/switch_options/known_moves/chosen_actions), all
    reflecting state as of the START of that turn - i.e. BEFORE that turn's
    own chosen_actions were applied, so a turn's window never leaks its own
    outcome into what was "available" going in.

    Filters `events` down to this match by its own `match` field - pass the
    FULL events list for the job (or at least the full list for one match),
    same calling convention as backend/analytics.compute_report() and
    friends. See build_decision_windows_for_job below for the multi-match,
    whole-job entry point.

    Returns [] if this match has no field_state events with a `turn` number
    at all - see module docstring for why (nothing to key turns off, most
    notably true of Showdown-imported matches today)."""
    match_events = sorted(
        (e for e in events if e.get("match") == match_number), key=ts)

    brought = {"player": [], "opponent": []}
    for e in match_events:
        if str(e.get("event", "")).strip() == "team_preview":
            brought["player"] = _names_of(e.get("player_brought")) or _names_of(e.get("player_team"))
            brought["opponent"] = _names_of(e.get("opponent_brought")) or _names_of(e.get("opponent_team"))
            break

    # Pass 1: bucket every action/field_state update under the turn number
    # active at the time it happened.
    current_turn = None
    turns = {}
    order = []

    def bucket(t):
        if t not in turns:
            turns[t] = {"actions": {"player": [], "opponent": []}, "active_updates": []}
            order.append(t)
        return turns[t]

    for e in match_events:
        kind = str(e.get("event", "")).strip()
        if kind == "team_preview":
            continue
        if kind == "field_state":
            t = _normalize_turn(e.get("turn"))
            if t is not None:
                current_turn = t
            if current_turn is None:
                continue  # a pre-turn-1 field_state (rare) has nothing to attach to
            bucket(current_turn)["active_updates"].append({
                "player": _names_of(e.get("player_active")),
                "opponent": _names_of(e.get("opponent_active")),
            })
            continue
        side = e.get("actor")
        if side not in ("player", "opponent") or current_turn is None:
            continue
        b = bucket(current_turn)
        if kind == "pokemon_sent_out" and e.get("pokemon"):
            b["actions"][side].append({"type": "switch", "pokemon": e["pokemon"]})
        elif kind == "move_used" and e.get("pokemon"):
            b["actions"][side].append({"type": "move", "pokemon": e["pokemon"], "move": _move_name(e)})
        elif kind == "pokemon_fainted" and e.get("pokemon"):
            b["actions"][side].append({"type": "fainted", "pokemon": e["pokemon"]})

    if not order:
        return []
    order.sort()

    # Pass 2: walk turns in order. field_state's active-Pokemon info describes
    # the board AS OF this turn (it's a snapshot taken during the turn, not an
    # outcome of it) so it's applied FIRST, before this turn's window is
    # captured. Chosen-action effects (faints/switches/newly-revealed moves)
    # are the OUTCOME of the turn's decisions, so they're applied AFTER the
    # snapshot - they inform the NEXT turn's available options, never leaking
    # into this turn's own "what was available going in."
    fainted = {"player": set(), "opponent": set()}
    known_moves = {"player": {}, "opponent": {}}
    active = {"player": [], "opponent": []}

    windows = []
    for t in order:
        b = turns[t]
        for upd in b["active_updates"]:
            if upd["player"]:
                active["player"] = upd["player"]
            if upd["opponent"]:
                active["opponent"] = upd["opponent"]

        windows.append({
            "turn": t,
            "match": match_number,
            "player": _side_snapshot("player", active, fainted, known_moves, brought, b["actions"]["player"]),
            "opponent": _side_snapshot("opponent", active, fainted, known_moves, brought, b["actions"]["opponent"]),
        })

        for side in ("player", "opponent"):
            for act in b["actions"][side]:
                if act["type"] == "fainted":
                    fainted[side].add(act["pokemon"])
                elif act["type"] == "switch":
                    mon = act["pokemon"]
                    if mon not in active[side]:
                        active[side] = active[side] + [mon]
                elif act["type"] == "move" and act.get("move"):
                    lst = known_moves[side].setdefault(act["pokemon"], [])
                    if act["move"] not in lst:
                        lst.append(act["move"])
            _cap_active(active, fainted, side)

    return windows


def build_decision_windows_for_job(events):
    """All matches in one events.json, flattened into a single list (each
    window already carries its own `match` number) - the same "compute
    across every match, let the caller filter by match" convention as
    backend/analytics.compute_match_list. This is what the backend endpoint
    calls.

    group_by_match() has a fallback path (segmenting at each team_preview)
    for events with no `match` field at all - those events won't satisfy
    build_decision_windows' own `e.get("match") == match_number` filter, so
    each group's events are shallow-copied with `match` stamped onto them
    before being handed off, rather than silently returning nothing for
    that match."""
    groups = group_by_match(events)
    out = []
    for m in sorted(groups.keys()):
        stamped = [e if e.get("match") == m else {**e, "match": m} for e in groups[m]]
        out.extend(build_decision_windows(stamped, m))
    return out
