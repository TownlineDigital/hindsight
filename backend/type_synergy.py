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

score_selection()/best_selection()/preview_skill() (added 2026-07-09, direct
user request for a "Team Preview Skill Score": "How close was the player's
chosen 4 to the best available 4, using only information visible at team
preview?") extend this same layer: instead of just describing the brought-4
that actually happened, they enumerate every one of the 6-choose-4 = 15
possible selections from the full team_preview roster, score each the same
way, and compare the player's actual pick against the best-scoring
alternative. See preview_skill()'s own docstring for exactly what's captured
vs explicitly out of scope pending moveset/ability/item/speed data.
"""

import itertools
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


def score_selection(candidate: list, opponent_brought: list) -> dict | None:
    """0-100 composite score for how good a candidate brought-4 looks against
    a specific opponent brought-4, using only typing (Phase 1 - see module
    docstring). Two components, combined 65/35:

      - offense (65%): fraction of the opponent's 4 that `candidate` has a
        >=2x type-answer to (reuses _type_answers) - this is "Threat
        Coverage," the single biggest lever in the user's own requested
        formula (25 of 100 points in their suggested breakdown - the largest
        individual category).
      - defense (35%): team_risk(candidate)'s composite shared-weakness
        score, inverted and smoothly decayed (1 / (1 + risk_score)) rather
        than hard-capped, so a very loose build still resolves to some low
        score instead of clipping at 0. This stands in for what the user
        separately called Defensive Stability + Redundancy Penalty +
        Unanswered Threat Penalty - already computed by team_risk(), not
        reinvented here.

    Returns None (never a guess) if none of the opponent's 4 resolve to a
    known type - matches team_risk()/team_matchup()'s "report as unresolved"
    discipline throughout this module.
    """
    answers = _type_answers(candidate, opponent_brought)
    opp_resolved = len(answers)
    if not opp_resolved:
        return None
    coverage_n = sum(1 for v in answers.values() if v)
    offense = coverage_n / opp_resolved

    risk = team_risk(candidate)
    defense = 1 / (1 + risk["risk_score"])

    score = round(100 * (0.65 * offense + 0.35 * defense), 1)
    return {
        "score": score,
        "offense_pct": round(offense * 100, 1),
        "defense_risk_score": risk["risk_score"],
        "opponent_coverage": f"{coverage_n}/{opp_resolved}",
    }


def best_selection(team_of_six: list, opponent_brought: list) -> list:
    """Scores every possible 4-of-6 selection from `team_of_six` (C(6,4)=15
    when it's a genuine full 6) against `opponent_brought`, via
    score_selection(). Returns a list of {"candidate": [...], **score} dicts
    sorted best-first; candidates score_selection() can't resolve at all are
    skipped rather than guessed. Pure candidate generation + scoring - never
    reads `winner`, same objective-team-preview-layer contract as
    team_matchup()."""
    results = []
    for combo in itertools.combinations(team_of_six, 4):
        scored = score_selection(list(combo), opponent_brought)
        if scored is None:
            continue
        results.append({"candidate": list(combo), **scored})
    results.sort(key=lambda r: -r["score"])
    return results


# (max_regret_inclusive, label) - the user's own suggested Preview Regret
# buckets ("0-5 regret: Excellent preview", "6-12: Good", "13-20:
# Questionable", "21+: Major preview mistake"), applied on this function's
# 0-100 score scale.
_REGRET_BUCKETS = [
    (5, "Excellent preview"),
    (12, "Good preview"),
    (20, "Questionable preview"),
]


def _regret_category(regret: float) -> str:
    for threshold, label in _REGRET_BUCKETS:
        if regret <= threshold:
            return label
    return "Major preview mistake"


def preview_skill(team_of_six: list, actual_brought: list, opponent_brought: list) -> dict | None:
    """The Team Preview Skill Score (added 2026-07-09, direct user request -
    full "Team Preview Skill Score" / "Preview Regret" framework). Answers:
    "how close was the player's chosen 4 to the best available 4, using only
    information visible at team preview" - deliberately blind to `winner`,
    same objective-team-preview-layer contract as team_matchup()/team_risk().

    Needs a genuine 6-mon team_of_six (the full 15-way enumeration only makes
    sense from a real 6) and a resolved 4-mon actual_brought/opponent_brought
    - returns None (not a partial/guessed score) otherwise, same "report as
    unresolved, never guess" discipline as the rest of this module. This is
    exactly why analytics.py only calls this when player_team_known (see
    compute_opponent_strength) - it's also why a match hit by the player-
    brought-<4 extraction gap (see ARCHITECTURE_HANDOFF.md) correctly gets no
    preview_skill rather than a misleading one.

    Deliberately OUT OF SCOPE (Phase 1, type-chart only - see module docstring
    and team_matchup()'s own docstring for the fuller rationale): Speed
    Control, true Win Condition detection (Trick Room/Tailwind/redirection
    roles), Overprediction Risk, and opponent bring-PROBABILITY weighting
    (vs. just what they actually brought, which is all this function uses)
    all need moveset/ability/item/speed-tier/usage data that doesn't exist
    anywhere in this codebase yet - see ARCHITECTURE_HANDOFF.md's Phase 2
    roadmap. What IS captured: Threat Coverage and Defensive Stability/
    Redundancy, via score_selection()'s offense/defense terms.
    """
    if len(set(team_of_six)) != 6 or len(actual_brought) != 4 or not opponent_brought:
        return None

    ranked = best_selection(team_of_six, opponent_brought)
    if not ranked:
        return None
    best = ranked[0]

    actual_scored = score_selection(actual_brought, opponent_brought)
    if actual_scored is None:
        return None

    regret = round(best["score"] - actual_scored["score"], 1)
    skill_pct = round((actual_scored["score"] / best["score"]) * 100, 1) if best["score"] else None

    # Rank of the actual selection among all scored candidates (1 = best) -
    # ties broken by score only, so an actual selection that TIES the best
    # score is rank 1, not penalized for being a different 4 of equal value.
    actual_set = frozenset(actual_brought)
    rank = next((i + 1 for i, r in enumerate(ranked) if frozenset(r["candidate"]) == actual_set), None)

    # "Best alternative" - the top-scoring candidate, framed as a one-mon
    # swap when it differs from the actual selection by exactly one Pokemon
    # (the readable "Instead of bringing X, consider Y" case from the user's
    # own example output), else just the full alternative 4.
    best_alternative = None
    if frozenset(best["candidate"]) != actual_set:
        added = [p for p in best["candidate"] if p not in actual_set]
        removed = [p for p in actual_brought if p not in set(best["candidate"])]
        one_for_one = len(added) == 1 and len(removed) == 1
        best_alternative = {
            "candidate": best["candidate"],
            "score": best["score"],
            "swap_out": removed[0] if one_for_one else None,
            "swap_in": added[0] if one_for_one else None,
        }

    return {
        "selected_score": actual_scored["score"],
        "best_score": best["score"],
        "regret": regret,
        "regret_category": _regret_category(regret),
        "skill_pct": skill_pct,
        "rank_of_selected": rank,
        "candidates_scored": len(ranked),
        "best_alternative": best_alternative,
    }
