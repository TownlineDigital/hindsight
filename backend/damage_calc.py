"""
Gen 9 doubles damage calculator - Phase 2 of the live-coaching/optimal-play
roadmap (see ARCHITECTURE_HANDOFF.md §18 for Phase 1's data foundation,
§19 for this phase). Ported directly into Python rather than wrapping the
community-standard `@smogon/calc` npm package: this project's backend is
Python/FastAPI, `@smogon/calc` is JS, and this sandbox has a documented
`npm install` 403 restriction that would have blocked building/testing a
Node-subprocess integration end to end. Confirmed with the user (2026-07-09,
`AskUserQuestion`: "Port the formula into Python (Recommended)") before
building this instead of a JS wrapper.

The formula implemented here is the same publicly-documented Gen 9 damage
formula (Bulbapedia's "Damage" article; unchanged in its core shape since
Gen 3, extended for Gen 9 specifics like same-type Terastallization) that
`@smogon/calc` itself implements - not a novel or guessed-at formula.

Deliberately decoupled from any one data source: every function here takes
plain numbers/strings/dicts the caller supplies (base stats, IVs, EVs, a
move's power/type/category), not a fetch call into meta/<format>.json or
backend/pokedex.py. The one exception is type-effectiveness, which reuses
backend/pokedex.py's existing `type_multiplier()` / `TYPE_CHART` rather than
duplicating that data a third time (meta_build.py's PokeAPI type_chart is a
second, richer copy already; pokedex.py's is the "offline, always available"
one type_synergy.py already depends on, so this module follows the same
convention rather than inventing a fourth). This mirrors type_synergy.py's
"objective, inspectable, works offline" design - a caller wires this up to
real Pokemon (Phase 1's meta_build.py base_stats + backend/pokedex.py types),
but this module itself has no import-time dependency on match data.

=== What's modeled ===
- Full stat calculation from base stats + IVs + EVs + level + nature
  (`calc_stats`), including the Gen "floor twice" rounding rule.
- Core damage formula: level/power/Atk/Def base term, STAB (1.5x, 2x with
  Adaptability, plus Gen 9's same-type Terastallization bonus and its
  interaction with Adaptability), type effectiveness (dual-typing, 0x
  immunities), the doubles/multi-target 0.75x spread-move reduction,
  weather (Sun/Rain boosting or halving Fire/Water moves; Sandstorm/Snow
  boosting Rock/Ice Sp.Def/Def respectively), burn halving physical damage
  (unless Guts), a small set of real item/ability damage modifiers (Life
  Orb, Choice Band/Specs, Expert Belt, Adaptability, Guts), critical hits
  (1.5x, optional), and the real 16-value 0.85-1.00 random damage spread
  (not just a single "average" number).
- Stat stage boosts/drops (-6 to +6) on the attacking/defending stat used.

=== What's explicitly NOT modeled (Phase 2 scope, not a silent gap) ===
- Ability/item interactions beyond the small set above: Multiscale, Ice
  Face, Solid Rock/Filter/Tinted Lens, Thick Fat, weather-setting abilities
  themselves (weather is a plain field input here, not derived from an
  ability), Technician, Sheer Force, and many more real Gen 9 interactions.
- Screens (Reflect/Light Screen/Aurora Veil), Friend Guard, Terrain.
- Multi-hit moves, secondary effects, and moves whose base power varies by
  field state (e.g. Weather Ball, Facade while statused).
- Freeze-Dry's water-type-takes-super-effective-ice special case.
- Bulbapedia's exact multi-stage intermediate-flooring order: this module
  combines every non-random modifier into one float and floors once per
  random roll, rather than flooring after each individual modifier group
  the way the cartridge/Showdown do internally. This can very rarely put a
  roll's result off by 1 HP at a rounding boundary versus Showdown's own
  calculator - a known, named simplification, not an unnoticed bug.

Callers should treat a missing modifier here as "unmodified," never as an
error - an unrecognized ability/item string is simply ignored (falls
through to no bonus), matching this project's existing "don't guess, don't
crash" convention (see meta_build.py's Smogon parsers for the same pattern).
"""

from . import pokedex

STAT_KEYS = ("hp", "attack", "defense", "special-attack", "special-defense", "speed")
_SHORT = {
    "hp": "hp", "attack": "atk", "defense": "def",
    "special-attack": "spa", "special-defense": "spd", "speed": "spe",
}

# nature -> (boosted_short_stat, lowered_short_stat) or None for a neutral nature.
NATURES = {
    "Hardy": None, "Lonely": ("atk", "def"), "Brave": ("atk", "spe"),
    "Adamant": ("atk", "spa"), "Naughty": ("atk", "spd"),
    "Bold": ("def", "atk"), "Docile": None, "Relaxed": ("def", "spe"),
    "Impish": ("def", "spa"), "Lax": ("def", "spd"),
    "Timid": ("spe", "atk"), "Hasty": ("spe", "def"), "Serious": None,
    "Jolly": ("spe", "spa"), "Naive": ("spe", "spd"),
    "Modest": ("spa", "atk"), "Mild": ("spa", "def"), "Quiet": ("spa", "spe"),
    "Bashful": None, "Rash": ("spa", "spd"),
    "Calm": ("spd", "atk"), "Gentle": ("spd", "def"), "Sassy": ("spd", "spe"),
    "Careful": ("spd", "spa"), "Quirky": None,
}

# Items/abilities with a real, simple damage-formula effect. Anything not
# listed here is treated as having no damage-formula effect (see module
# docstring's "don't guess, don't crash" note) - most items/abilities
# genuinely don't affect this formula directly (they matter for switching,
# status, etc., which this module doesn't model at all).
_DAMAGE_ITEMS = {"Life Orb": 1.3, "Expert Belt": None}  # Expert Belt handled specially (super-effective only)
_CHOICE_ITEMS = {"Choice Band": "physical", "Choice Specs": "special"}


def nature_multiplier(nature, stat_short):
    """1.1 / 0.9 / 1.0 for a boosted/lowered/neutral stat under `nature`.
    Unrecognized nature name -> neutral (1.0), never an error."""
    entry = NATURES.get(nature)
    if not entry:
        return 1.0
    boost, lower = entry
    if stat_short == boost:
        return 1.1
    if stat_short == lower:
        return 0.9
    return 1.0


def calc_stats(base_stats: dict, level: int = 50, ivs: dict = None, evs: dict = None, nature: str = None) -> dict:
    """Final in-battle stats from base stats + IVs + EVs + level + nature.

    `base_stats`/`ivs`/`evs` all use the exact PokeAPI-style keys
    meta_build.py's fetch_pokedex() stores ("hp", "attack", "defense",
    "special-attack", "special-defense", "speed") - see Phase 1
    (ARCHITECTURE_HANDOFF.md §18a). `ivs` defaults to 31 in every stat and
    `evs` to 0 in every stat when not given (a reasonable "perfect IVs, no
    EVs invested" default for a quick lookup, not a claim about what any
    specific real Pokemon is actually running). `level` defaults to 50 -
    standard VGC doubles level, not the mainline-game default of 100.

    Uses the real "floor twice" Gen stat formula (floor the base/IV/EV/level
    term, add 5 (or +level+10 for HP), THEN multiply by nature and floor
    again) - not a shortcut single-pass approximation.
    """
    ivs = ivs or {}
    evs = evs or {}
    out = {}
    for key in STAT_KEYS:
        base = base_stats.get(key, 0)
        iv = ivs.get(key, 31)
        ev = evs.get(key, 0)
        if key == "hp":
            if base == 0:
                out[key] = 0
            else:
                out[key] = ((2 * base + iv + ev // 4) * level) // 100 + level + 10
        else:
            inner = ((2 * base + iv + ev // 4) * level) // 100 + 5
            mult = nature_multiplier(nature, _SHORT[key])
            out[key] = int(inner * mult)
    return out


def _stage_multiplier(stage: int) -> float:
    """Standard Gen stat-stage multiplier, -6..+6. Anything outside that
    range is clamped rather than raising - a caller passing a raw sum of
    boosts/drops that overshot doesn't crash a whole calculation over it."""
    stage = max(-6, min(6, stage))
    if stage >= 0:
        return (2 + stage) / 2
    return 2 / (2 - stage)


def type_effectiveness(move_type: str, defend_types) -> float:
    """Thin wrapper on backend/pokedex.py's type_multiplier() - see this
    module's docstring for why that source specifically. 0 means immune."""
    return pokedex.type_multiplier(move_type, defend_types)


def calculate_damage(attacker: dict, defender: dict, move: dict, field: dict = None) -> dict:
    """The core Phase 2 entry point: full 16-value Gen 9 damage roll spread
    for one attack, plus convenience min/max/avg and %-of-defender-max-HP
    figures. See this module's docstring for exactly what is and isn't
    modeled.

    `attacker`: {"stats": {...from calc_stats...}, "types": [t1, t2?],
      "ability": str|None, "item": str|None, "status": "brn"|None,
      "tera_type": str|None, "is_tera": bool, "atk_stage": int, "spa_stage": int}
    `defender`: {"stats": {...}, "types": [t1, t2?], "tera_type": str|None,
      "is_tera": bool, "def_stage": int, "spd_stage": int}
    `move`: {"power": int, "type": str, "category": "physical"|"special",
      "is_spread": bool (multi-target move in doubles), "is_crit": bool}
    `field`: {"weather": "sun"|"rain"|"sand"|"snow"|None, "targets_count": int}
      - `targets_count` > 1 together with `move["is_spread"]` applies the
      0.75x doubles spread-move reduction; a spread move that only actually
      hit one target (the other already fainted/switched) should pass
      targets_count=1, matching the real in-game rule.

    A missing/zero base power (e.g. a status move) returns an all-zero
    result rather than raising - a caller doesn't need to pre-filter out
    non-damaging moves.
    """
    field = field or {}
    move = move or {}
    power = move.get("power") or 0
    if power <= 0:
        return {"rolls": [0] * 16, "min": 0, "max": 0, "avg": 0.0,
                "min_pct": 0.0, "max_pct": 0.0, "defender_hp": defender.get("stats", {}).get("hp", 0)}

    category = move.get("category", "physical")
    move_type = (move.get("type") or "").lower()
    level = attacker.get("level", 50)

    atk_key = "attack" if category == "physical" else "special-attack"
    def_key = "defense" if category == "physical" else "special-defense"
    atk = attacker.get("stats", {}).get(atk_key, 0)
    defn = defender.get("stats", {}).get(def_key, 0)
    atk = int(atk * _stage_multiplier(attacker.get(f"{_SHORT[atk_key]}_stage", 0)))
    defn = int(defn * _stage_multiplier(defender.get(f"{_SHORT[def_key]}_stage", 0)))

    defender_types = list(defender.get("types") or [])
    if defender.get("is_tera") and defender.get("tera_type"):
        defender_types = [defender["tera_type"]]

    weather = field.get("weather")
    if weather == "sand" and category == "special" and "rock" in [t.lower() for t in defender_types]:
        defn = int(defn * 1.5)
    if weather == "snow" and category == "physical" and "ice" in [t.lower() for t in defender_types]:
        defn = int(defn * 1.5)

    defn = max(1, defn)
    atk = max(1, atk)

    term1 = (2 * level) // 5 + 2
    step = (term1 * power * atk) // defn
    base = step // 50 + 2

    modifier = 1.0

    # doubles/multi-target spread-move reduction
    if move.get("is_spread") and field.get("targets_count", 1) > 1:
        modifier *= 0.75

    # weather (fire/water boost/halve only - sand/snow's defensive effect is
    # already folded into `defn` above)
    if weather == "sun":
        if move_type == "fire":
            modifier *= 1.5
        elif move_type == "water":
            modifier *= 0.5
    elif weather == "rain":
        if move_type == "water":
            modifier *= 1.5
        elif move_type == "fire":
            modifier *= 0.5

    if move.get("is_crit"):
        modifier *= 1.5

    # STAB, incl. Gen 9 same-type Terastallization + Adaptability interaction
    original_types = [t.lower() for t in (attacker.get("types") or [])]
    ability = attacker.get("ability")
    stab = 1.0
    if attacker.get("is_tera") and attacker.get("tera_type"):
        tera_type = attacker["tera_type"].lower()
        if tera_type == move_type:
            stab = 2.0 if tera_type in original_types else 1.5
        elif move_type in original_types:
            stab = 1.5
    elif move_type in original_types:
        stab = 1.5
    if ability == "Adaptability" and stab > 1.0:
        stab = 2.25 if stab >= 2.0 else 2.0
    modifier *= stab

    # type effectiveness
    type_mult = type_effectiveness(move_type, defender_types)
    modifier *= type_mult

    # burn (physical only, negated by Guts)
    if attacker.get("status") == "brn" and category == "physical" and ability != "Guts":
        modifier *= 0.5

    # item modifiers
    item = attacker.get("item")
    if item == "Life Orb":
        modifier *= 1.3
    elif item in _CHOICE_ITEMS and _CHOICE_ITEMS[item] == category:
        modifier *= 1.5
    elif item == "Expert Belt" and type_mult > 1.0:
        modifier *= 1.2

    if type_mult == 0:
        rolls = [0] * 16
    else:
        rolls = []
        for pct in range(85, 101):
            dmg = int(base * modifier * (pct / 100))
            rolls.append(max(1, dmg))

    defender_hp = defender.get("stats", {}).get("hp", 0)
    result = {
        "rolls": rolls,
        "min": min(rolls),
        "max": max(rolls),
        "avg": round(sum(rolls) / len(rolls), 2),
        "defender_hp": defender_hp,
    }
    if defender_hp > 0:
        result["min_pct"] = round(result["min"] / defender_hp * 100, 1)
        result["max_pct"] = round(result["max"] / defender_hp * 100, 1)
    else:
        result["min_pct"] = result["max_pct"] = 0.0
    return result
