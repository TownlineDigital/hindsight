"""
Scores a brought-4 team on type-overlap risk - a real, well-known VGC team-
building liability: if 2+ of your 4 Pokemon share a weakness, a single spread
move (hits both active Pokemon) or a well-picked attacker threatens your whole
side at once, and it's an easy read for your opponent to play around.

This is deliberately simple and inspectable (not a black box): it's built
straight from the standard type chart (pokedex.py), not usage stats or machine
learning. Lower score = tighter, safer construction. Higher score = more
exploitable overlap. See analytics.compute_opponent_strength() for how this
gets correlated against actual match outcomes in the player's own data - that
correlation is what makes this "tangible" rather than just type-chart trivia.
"""

from collections import Counter
from . import pokedex


def team_risk(species: list) -> dict:
    """species: list of Pokemon names (the brought 4, ideally). Returns a
    breakdown plus a single composite score. Unknown species (not in
    pokedex.SPECIES_TYPES) are skipped and reported under "unresolved" rather
    than guessed - never silently treated as having no weaknesses."""
    resolved = []
    unresolved = []
    for name in species:
        types = pokedex.SPECIES_TYPES.get(name)
        if types:
            resolved.append((name, types))
        else:
            unresolved.append(name)

    shared = Counter()      # attacking type -> how many resolved team members are weak to it
    quad_weak = []          # (name, type) pairs where a team member is 4x weak
    per_member = {}
    for name, types in resolved:
        w = pokedex.weaknesses(types)
        per_member[name] = w
        for atk, mult in w.items():
            shared[atk] += 1
            if mult >= 4:
                quad_weak.append((name, atk))

    # "extra" exposure per type: 1 member weak to a type is normal (every Pokemon has
    # weaknesses); 2+ sharing the SAME weakness is the actual liability being measured.
    overlap_types = {t: c for t, c in shared.items() if c >= 2}
    shared_weakness_score = sum(c - 1 for c in overlap_types.values())
    composite = shared_weakness_score + 1.5 * len(quad_weak)

    return {
        "resolved": [n for n, _ in resolved],
        "unresolved": unresolved,
        "coverage": f"{len(resolved)}/{len(species)}",
        "shared_weaknesses": {t: c for t, c in sorted(overlap_types.items(), key=lambda kv: -kv[1])},
        "quad_weaknesses": [{"pokemon": n, "type": t} for n, t in quad_weak],
        "risk_score": round(composite, 2),
    }
