"""
Item-reveal detection - the first slice of Phase 3 (build/EV inference) in
the live-coaching/optimal-play roadmap (ARCHITECTURE_HANDOFF.md §18/§19).
Direct user request, verbatim: "damage with items like focus sash and
choice scarf and life orb until we know the opponent has it on their
pokemon" - confirmed via `AskUserQuestion`: **"Default to 'no item' until
confirmed (Recommended)"**.

This module answers exactly one question: for a given match's events, which
Pokemon had which item ACTUALLY CONFIRMED by Showdown's own protocol -
never a guess from Smogon's popular-builds data (that's a separate,
explicitly probabilistic use of Phase 1's data, not this module's job), and
never inferred from HP math (a Pokemon surviving at 1 HP COULD be Focus
Sash, but could also be Sturdy, Endure, a berry, or simply not having taken
lethal damage - Showdown's own protocol already tells us definitively which
one it was via -activate/-enditem, so there's no need to guess when real
evidence exists).

Reads `item_or_ability_activated` events produced by showdown_import.py
(its -damage/-heal/-ability/-item/-activate/-enditem handlers, the latter
three extended 2026-07-09 specifically to support this module - see that
file's own comments at each handler). Every one of these events with a
structured `item` field is Showdown's OWN protocol explicitly naming the
item - none of this module invents or infers anything:

  - A direct `-item` reveal (e.g. Trick/Switcheroo swapping items, or a
    scouted Air Balloon) - `detail` is `"item: <name>"`.
  - Damage/heal explicitly attributed to an item via Showdown's own
    `[from] item: X` protocol tag (Life Orb recoil, Leftovers/berry heals,
    Rocky Helmet, etc.) - `detail` contains `"(recoil)"`/`"(heal)"`.
  - A `-activate`/`-enditem` item trigger (Focus Sash saving a Pokemon,
    a berry being eaten, Air Balloon popping) - `detail` contains
    `"(activated)"`/`"(consumed)"`.

A Pokemon with no matching event in its match simply doesn't appear in this
module's output - the caller (e.g. code building an `attacker`/`defender`
dict for `damage_calc.calculate_damage()`) should treat "not in this dict"
as "item unknown." `damage_calc.py` already treats a missing/`None` `item`
key as "no item bonus" by default (see its own module docstring's "don't
guess, don't crash" convention), so the "default to no item until
confirmed" behavior this module exists for falls out naturally from
composing the two modules together - no special-casing needed in either
one. See this file's own module-level example below for exactly how that
composition looks in practice.

Example composition with damage_calc.py:

    items = item_inference.revealed_items(match_events)
    attacker_item = items.get("opponent:Garchomp")   # None if unconfirmed
    attacker = {"stats": ..., "types": ..., "item": attacker_item, ...}
    result = damage_calc.calculate_damage(attacker, defender, move, field)

If `attacker_item` is `None` here (nothing in this match confirmed an
item for the opponent's Garchomp), `calculate_damage()` simply applies no
item-based bonus at all - the honest, conservative default, never a guess
at "well, 60% of Garchomp run Life Orb" blended silently into a "real"
damage number.
"""


def revealed_items(match_events: list) -> dict:
    """{pokemon_key: item_name} for every item Showdown's own protocol
    explicitly confirmed during this match - see module docstring for the
    exact evidence types recognized. `pokemon_key` is `f"{actor}:{pokemon}"`
    (e.g. `"opponent:Garchomp"`) rather than species alone, since the same
    species could in principle appear tracked under both actors across a
    combined events.json (unrelated matches), and keying by actor keeps
    this function safe to call on a whole events.json, not just one
    match's slice, without cross-contaminating sides.

    Only pass events belonging to the match(es) you actually want items
    for - a fresh battle means a fresh, possibly different, held item even
    on the same species, so mixing events from multiple real matches into
    one `revealed_items()` call only makes sense if the caller genuinely
    wants "any item ever seen on this species across all these matches,"
    which is a different (and much less precise) question than "what is
    this Pokemon holding in THIS match."

    Unrecognized/malformed events are silently skipped, never guessed at -
    the same "don't guess, don't crash" convention this project holds
    itself to everywhere else (see meta_build.py's Smogon parsers,
    damage_calc.py's unrecognized-ability/item handling, etc.).
    """
    out = {}
    for e in match_events:
        if not isinstance(e, dict) or e.get("event") != "item_or_ability_activated":
            continue
        item = e.get("item")
        actor = e.get("actor")
        pokemon = e.get("pokemon")
        if not item or not actor or not pokemon:
            continue
        out[f"{actor}:{pokemon}"] = item
    return out


def item_for(match_events: list, actor: str, pokemon: str):
    """Convenience single-lookup wrapper on revealed_items() - returns the
    confirmed item name, or None if nothing in this match confirmed one for
    this exact actor+pokemon. None is the correct, honest answer for "we
    don't know" - never guess a popular build here (see this module's own
    docstring for why); a caller wanting a Smogon-popularity-based GUESS
    for planning purposes should say so explicitly at the call site (e.g.
    labeled "likely item (unconfirmed)" in any UI), never silently blended
    with this function's confirmed-only results.
    """
    return revealed_items(match_events).get(f"{actor}:{pokemon}")
