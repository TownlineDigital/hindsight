"""
Static Pokemon type reference data - the standard 18-type effectiveness chart
(unchanged since Fairy was added in Gen 6) plus a species -> type(s) lookup for
the Pokemon that actually show up in this project's matches.

Why hardcoded instead of pulling from meta_build.py's PokeAPI fetch: the type
chart never changes, and this way opponent-strength scoring (type_synergy.py)
works completely offline with zero setup - no meta/ folder, no network call,
no API key required. If meta/<format>.json exists (built via `py meta_build.py`)
and has richer/pokedex data, prefer that; SPECIES_TYPES below is the fallback
and the thing to extend if a new Pokemon shows up that isn't in it yet.

Adding a new species: just add one line, "Name": ("Type1",) or ("Type1", "Type2").
Unknown species are skipped (not guessed) by type_synergy.py's scoring - a
partial-coverage note is surfaced rather than silently wrong data.
"""

TYPES = ["normal", "fire", "water", "electric", "grass", "ice", "fighting", "poison",
         "ground", "flying", "psychic", "bug", "rock", "ghost", "dragon", "dark",
         "steel", "fairy"]

# attacking type -> {defending type: multiplier}, only non-1x entries listed
TYPE_CHART = {
    "normal":   {"rock": 0.5, "steel": 0.5, "ghost": 0},
    "fire":     {"fire": 0.5, "water": 0.5, "grass": 2, "ice": 2, "bug": 2,
                 "rock": 0.5, "dragon": 0.5, "steel": 2},
    "water":    {"fire": 2, "water": 0.5, "grass": 0.5, "ground": 2, "rock": 2, "dragon": 0.5},
    "electric": {"water": 2, "electric": 0.5, "grass": 0.5, "ground": 0, "flying": 2, "dragon": 0.5},
    "grass":    {"fire": 0.5, "water": 2, "grass": 0.5, "poison": 0.5, "ground": 2,
                 "flying": 0.5, "bug": 0.5, "rock": 2, "dragon": 0.5, "steel": 0.5},
    "ice":      {"fire": 0.5, "water": 0.5, "grass": 2, "ice": 0.5, "ground": 2,
                 "flying": 2, "dragon": 2, "steel": 0.5},
    "fighting": {"normal": 2, "ice": 2, "poison": 0.5, "flying": 0.5, "psychic": 0.5,
                 "bug": 0.5, "rock": 2, "ghost": 0, "dark": 2, "steel": 2, "fairy": 0.5},
    "poison":   {"grass": 2, "poison": 0.5, "ground": 0.5, "rock": 0.5, "ghost": 0.5,
                 "steel": 0, "fairy": 2},
    "ground":   {"fire": 2, "electric": 2, "grass": 0.5, "poison": 2, "flying": 0,
                 "bug": 0.5, "rock": 2, "steel": 2},
    "flying":   {"electric": 0.5, "grass": 2, "fighting": 2, "bug": 2, "rock": 0.5, "steel": 0.5},
    "psychic":  {"fighting": 2, "poison": 2, "psychic": 0.5, "dark": 0, "steel": 0.5},
    "bug":      {"fire": 0.5, "grass": 2, "fighting": 0.5, "poison": 0.5, "flying": 0.5,
                 "psychic": 2, "ghost": 0.5, "dark": 2, "steel": 0.5, "fairy": 0.5},
    "rock":     {"fire": 2, "ice": 2, "fighting": 0.5, "ground": 0.5, "flying": 2,
                 "bug": 2, "steel": 0.5},
    "ghost":    {"normal": 0, "psychic": 2, "ghost": 2, "dark": 0.5},
    "dragon":   {"dragon": 2, "steel": 0.5, "fairy": 0},
    "dark":     {"fighting": 0.5, "psychic": 2, "ghost": 2, "dark": 0.5, "fairy": 0.5},
    "steel":    {"fire": 0.5, "water": 0.5, "electric": 0.5, "ice": 2, "rock": 2,
                 "steel": 0.5, "fairy": 2},
    "fairy":    {"fire": 0.5, "fighting": 2, "poison": 0.5, "dragon": 2, "dark": 2, "steel": 0.5},
}

# Species appearing in this project's matches so far. Extend as new ones show up.
SPECIES_TYPES = {
    "Aerodactyl": ("rock", "flying"),
    "Archaludon": ("steel", "dragon"),
    "Basculegion": ("water", "ghost"),
    "Basculin": ("water",),
    "Blaziken": ("fire", "fighting"),
    "Ceruledge": ("fire", "ghost"),
    "Charizard": ("fire", "flying"),
    "Duraludon": ("steel", "dragon"),
    "Excadrill": ("ground", "steel"),
    "Farigiraf": ("normal", "psychic"),
    "Froslass": ("ice", "ghost"),
    "Gallade": ("psychic", "fighting"),
    "Garchomp": ("dragon", "ground"),
    "Gengar": ("ghost", "poison"),
    "Girafarig": ("normal", "psychic"),
    "Glimmet": ("rock", "poison"),
    "Glimmora": ("rock", "poison"),
    "Grimmsnarl": ("dark", "fairy"),
    "Heracross": ("bug", "fighting"),
    "Hydreigon": ("dark", "dragon"),
    "Incineroar": ("fire", "dark"),
    "Kangaskhan": ("normal",),
    "Kingambit": ("dark", "steel"),
    "Kommo-o": ("dragon", "fighting"),
    "Lycanroc": ("rock",),
    "Lycanroc-Dusk": ("rock",),
    "Mawile": ("steel", "fairy"),
    "Metagross": ("steel", "psychic"),
    "Ninetales-Alola": ("ice", "fairy"),
    "Overqwil": ("dark", "poison"),
    "Pelipper": ("water", "flying"),
    "Pinsir": ("bug",),
    "Raichu": ("electric",),
    "Rotom-Wash": ("electric", "water"),
    "Scizor": ("bug", "steel"),
    "Scovillain": ("grass", "fire"),
    "Sinistcha": ("grass", "ghost"),
    "Slowking-Galar": ("poison", "psychic"),
    "Sneasler": ("fighting", "poison"),
    "Snorlax": ("normal",),
    "Staraptor": ("normal", "flying"),
    "Swampert": ("water", "ground"),
    "Sylveon": ("fairy",),
    "Talonflame": ("fire", "flying"),
    "Tauros": ("normal",),
    "Tauros-Paldea-Water": ("fighting", "water"),
    "Venusaur": ("grass", "poison"),
    "Whimsicott": ("grass", "fairy"),
    "Zoroark-Hisui": ("normal", "ghost"),
}


def type_multiplier(attack_type: str, defend_types) -> float:
    """Damage multiplier of one attacking type against a Pokemon with 1-2 defending types."""
    row = TYPE_CHART.get(attack_type, {})
    mult = 1.0
    for t in defend_types:
        mult *= row.get(t, 1)
    return mult


def weaknesses(defend_types) -> dict:
    """{attacking_type: multiplier} for every attacking type that's super-effective (>1x)."""
    out = {}
    for atk in TYPES:
        m = type_multiplier(atk, defend_types)
        if m > 1:
            out[atk] = m
    return out
