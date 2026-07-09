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

Both team_risk() (this file, pre-existing) and team_matchup() (added
2026-07-09) live entirely in the OBJECTIVE TEAM PREVIEW EVALUATION layer -
"was this a strong decision with the information available," judged only
from team-preview/typing data, deliberately blind to `winner` or any
turn-by-turn battle data. The companion OUTCOME EVALUATION layer (judging
execution - move selection, positioning, predictions, resource management,
adaptation - after the fact) is strategic_analysis.py's six per-turn reports,
which DO read full battle data on purpose. See ARCHITECTURE_HANDOFF.md for
where this split is documented end to end.
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


def _type_answers(attackers: list, defenders: list) -> dict:
    """For each defender, which attackers have an own-type "STAB" hit of 2x or
    more against it? {defender_name: [attacker names that threaten it]} -
    defenders/attackers with unresolved typing (not in pokedex.SPECIES_TYPES)
    are skipped, same "report as unresolved, never guess" rule as team_risk().
    """
    out = {}
    for d_name in defenders:
        d_types = pokedex.SPECIES_TYPES.get(d_name)
        if not d_types:
            continue
        answers = []
        for a_name in attackers:
            a_types = pokedex.SPECIES_TYPES.get(a_name)
            if not a_types:
                continue
            best = max(pokedex.type_multiplier(t, d_types) for t in a_types)
            if best >= 2:
                answers.append(a_name)
        out[d_name] = answers
    return out


def team_matchup(player_species: list, opponent_species: list) -> dict:
    """A coarse, type-chart-only cross-matchup between two brought teams -
    added 2026-07-09, direct user request for the Opponent Intel tab: "what
    pokemon we both brought and how it was advantageous or disadvantageous
    to us."

    This belongs entirely to the OBJECTIVE TEAM PREVIEW EVALUATION layer
    (added 2026-07-09, user-defined split): "was this a strong decision with
    the information available" - team preview, typing, archetypes - judged
    WITHOUT reference to how the battle actually went. That's why this
    function's signature only takes species lists, never `winner` or any
    turn/event data - deliberately structured so it CAN'T be biased by the
    result, matching the user's explicit requirement. The separate OUTCOME
    EVALUATION layer (execution: move selection, positioning, predictions,
    resource management, adaptation) already exists as strategic_analysis.py's
    six per-turn reports (speed_control/threat_pressure/resource_advantage/
    momentum/position_score/risk_management) + analytics.compute_battle_profile's
    rollup - those deliberately DO read full battle/turn data, since judging
    execution requires knowing what was executed. See ARCHITECTURE_HANDOFF.md
    for how the two layers are documented together.

    This is deliberately scoped down (Phase 1) within the team-preview layer:
    a Pokemon's actual moves don't have to match its own type (coverage moves
    are common), abilities/items/EVs/speed order all matter in a real matchup
    and none of that data exists in this project yet - see
    ARCHITECTURE_HANDOFF.md for the fuller "Team Choice Score" framework
    (coverage/threat coverage/synergy/win-condition/flexibility/prediction-
    dependence/opportunity-cost/Bayesian bring-probability) this stands in
    for, deferred as Phase 2 pending movesets + speed-tier + usage data.
    Treat "favorable" here as "on paper, by typing alone" - a hint, not a
    verdict.

    For each side, counts how many of the OTHER side's Pokemon are threatened
    (>=2x) by at least one of this side's own types - i.e. "how many of their
    4 do I have a real type-advantage answer to." Unresolved species (not in
    pokedex.SPECIES_TYPES) are excluded from both the numerator and
    denominator rather than guessed.
    """
    your_answers = _type_answers(player_species, opponent_species)     # opponent mon -> your answers
    their_answers = _type_answers(opponent_species, player_species)    # your mon -> their answers

    your_coverage_n = sum(1 for v in your_answers.values() if v)
    their_coverage_n = sum(1 for v in their_answers.values() if v)
    opp_resolved = len(your_answers)
    you_resolved = len(their_answers)

    verdict = None
    if opp_resolved and you_resolved:
        your_pct = your_coverage_n / opp_resolved
        their_pct = their_coverage_n / you_resolved
        diff = your_pct - their_pct
        if diff >= 0.25:
            verdict = "favorable"
        elif diff <= -0.25:
            verdict = "unfavorable"
        else:
            verdict = "even"

    return {
        "your_type_answers": your_answers,
        "their_type_answers": their_answers,
        "your_coverage": f"{your_coverage_n}/{opp_resolved}" if opp_resolved else None,
        "their_coverage": f"{their_coverage_n}/{you_resolved}" if you_resolved else None,
        "verdict": verdict,
    }
