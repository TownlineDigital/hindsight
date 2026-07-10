"""
Tests for backend/type_synergy.py's team_matchup() - the Objective Team
Preview Evaluation heuristic added 2026-07-09 (direct user request: "what
pokemon we both brought and how it was advantageous or disadvantageous to
us") - and score_selection()/best_selection()/preview_skill() (added
2026-07-09, direct user request for a "Team Preview Skill Score": "How close
was the player's chosen 4 to the best available 4, using only information
visible at team preview?"). Uses hand-picked species with well-known type
relationships rather than real match data, so the expected answers are
checkable by hand against pokedex.TYPE_CHART/SPECIES_TYPES (both static, so
hardcoded expected scores below won't drift the way real match data could).

Run: py -m unittest tests.test_type_synergy -v   (from poc-starter/)
"""

import inspect
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend import type_synergy  # noqa: E402


class TestTeamMatchup(unittest.TestCase):
    def test_one_sided_answer_is_reflected_in_coverage(self):
        # Garchomp (dragon/ground) has a same-type "STAB" hit (ground) that's
        # 2x super-effective into Metagross (steel/psychic) - ground vs steel
        # is 2x per pokedex.TYPE_CHART. Metagross has no own-type hit that's
        # super-effective back into Garchomp (steel is 0.5x dragon, 1x ground;
        # psychic is 1x/1x) - so this should read as fully one-sided.
        result = type_synergy.team_matchup(["Garchomp"], ["Metagross"])
        self.assertEqual(result["your_coverage"], "1/1")
        self.assertEqual(result["their_coverage"], "0/1")
        self.assertEqual(result["verdict"], "favorable")

    def test_symmetric_teams_are_even(self):
        # Same species on both sides can never favor either side.
        team = ["Incineroar", "Grimmsnarl"]
        result = type_synergy.team_matchup(team, list(team))
        self.assertEqual(result["your_coverage"], result["their_coverage"])
        self.assertIn(result["verdict"], (None, "even"))

    def test_unresolved_species_are_excluded_not_guessed(self):
        result = type_synergy.team_matchup(["NotARealPokemon"], ["Metagross"])
        self.assertEqual(result["your_type_answers"], {"Metagross": []})
        # The unresolved attacker contributes nothing and isn't silently
        # treated as a match - "no answer found" is correct here.
        self.assertNotIn("NotARealPokemon", result["their_type_answers"])

    def test_empty_inputs_return_no_verdict_not_a_crash(self):
        result = type_synergy.team_matchup([], [])
        self.assertIsNone(result["verdict"])
        self.assertEqual(result["your_type_answers"], {})
        self.assertEqual(result["their_type_answers"], {})

    def test_verdict_never_computed_from_fewer_than_both_sides_resolved(self):
        # Only the opponent side resolves to a real species - coverage on the
        # player side has nothing to divide by, so verdict must stay None
        # rather than dividing by zero or guessing.
        result = type_synergy.team_matchup(["NotARealPokemon"], ["Metagross"])
        self.assertIsNone(result["verdict"])


class TestScoreSelection(unittest.TestCase):
    def test_signature_cannot_see_the_winner(self):
        """Same structural guarantee as team_matchup - this stays in the
        Objective Team Preview Evaluation layer, so it must never grow a
        winner/result parameter."""
        params = set(inspect.signature(type_synergy.score_selection).parameters)
        self.assertEqual(params, {"candidate", "opponent_brought"})

    def test_single_mon_answer_scores_the_known_value(self):
        # Garchomp fully answers Metagross (offense 100%) but is itself
        # quad-weak to Ice (dragon x2 * ground x2) even alone, so
        # team_risk(["Garchomp"])["risk_score"] == 1.5, not 0 - this is a
        # real property of the static type chart, checked by hand.
        result = type_synergy.score_selection(["Garchomp"], ["Metagross"])
        self.assertEqual(result["offense_pct"], 100.0)
        self.assertEqual(result["defense_risk_score"], 1.5)
        self.assertEqual(result["score"], 79.0)  # 100*(0.65*1.0 + 0.35*(1/2.5))

    def test_returns_none_when_opponent_entirely_unresolved(self):
        self.assertIsNone(type_synergy.score_selection(["Garchomp"], ["NotARealPokemon"]))

    def test_score_is_bounded_0_to_100(self):
        for candidate in (["Garchomp"], ["Metagross", "Sylveon"], []):
            result = type_synergy.score_selection(candidate, ["Metagross", "Aerodactyl"])
            if result is not None:
                with self.subTest(candidate=candidate):
                    self.assertGreaterEqual(result["score"], 0)
                    self.assertLessEqual(result["score"], 100)


class TestBestSelection(unittest.TestCase):
    SIX = ["Garchomp", "Metagross", "Incineroar", "Grimmsnarl", "Sylveon", "Kingambit"]

    def test_enumerates_all_fifteen_combinations_of_a_real_six(self):
        ranked = type_synergy.best_selection(self.SIX, ["Aerodactyl"])
        self.assertEqual(len(ranked), 15)  # 6 choose 4
        seen = set()
        for r in ranked:
            self.assertEqual(len(r["candidate"]), 4)
            self.assertTrue(set(r["candidate"]).issubset(set(self.SIX)))
            seen.add(frozenset(r["candidate"]))
        self.assertEqual(len(seen), 15)  # every combination is distinct

    def test_sorted_best_first(self):
        ranked = type_synergy.best_selection(self.SIX, ["Aerodactyl"])
        scores = [r["score"] for r in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_empty_when_opponent_unresolved(self):
        self.assertEqual(type_synergy.best_selection(self.SIX, ["NotARealPokemon"]), [])


class TestPreviewSkill(unittest.TestCase):
    SIX = ["Garchomp", "Metagross", "Incineroar", "Grimmsnarl", "Sylveon", "Kingambit"]

    def test_signature_cannot_see_the_winner(self):
        params = set(inspect.signature(type_synergy.preview_skill).parameters)
        self.assertEqual(params, {"team_of_six", "actual_brought", "opponent_brought"})

    def test_zero_regret_when_actual_selection_is_already_best(self):
        best = type_synergy.best_selection(self.SIX, ["Aerodactyl"])[0]
        result = type_synergy.preview_skill(self.SIX, best["candidate"], ["Aerodactyl"])
        self.assertEqual(result["regret"], 0.0)
        self.assertEqual(result["regret_category"], "Excellent preview")
        self.assertEqual(result["rank_of_selected"], 1)
        self.assertEqual(result["skill_pct"], 100.0)
        self.assertIsNone(result["best_alternative"])

    def test_worst_selection_reports_full_regret_and_a_one_mon_swap(self):
        ranked = type_synergy.best_selection(self.SIX, ["Aerodactyl"])
        worst = ranked[-1]
        result = type_synergy.preview_skill(self.SIX, worst["candidate"], ["Aerodactyl"])
        self.assertEqual(result["regret"], round(ranked[0]["score"] - worst["score"], 1))
        self.assertEqual(result["regret_category"], "Major preview mistake")
        self.assertEqual(result["rank_of_selected"], len(ranked))
        self.assertIsNotNone(result["best_alternative"])
        # The worst and best 4-of-6 here differ by exactly one Pokemon, so
        # this should read as a single readable swap, not just "here's a
        # whole different 4."
        self.assertIsNotNone(result["best_alternative"]["swap_out"])
        self.assertIsNotNone(result["best_alternative"]["swap_in"])
        self.assertIn(result["best_alternative"]["swap_out"], worst["candidate"])
        self.assertNotIn(result["best_alternative"]["swap_out"], ranked[0]["candidate"])
        self.assertIn(result["best_alternative"]["swap_in"], ranked[0]["candidate"])
        self.assertNotIn(result["best_alternative"]["swap_in"], worst["candidate"])

    def test_regret_category_boundaries(self):
        # The user's own suggested buckets: 0-5 excellent, 6-12 good,
        # 13-20 questionable, 21+ major mistake - check every boundary.
        self.assertEqual(type_synergy._regret_category(0), "Excellent preview")
        self.assertEqual(type_synergy._regret_category(5), "Excellent preview")
        self.assertEqual(type_synergy._regret_category(5.01), "Good preview")
        self.assertEqual(type_synergy._regret_category(12), "Good preview")
        self.assertEqual(type_synergy._regret_category(12.01), "Questionable preview")
        self.assertEqual(type_synergy._regret_category(20), "Questionable preview")
        self.assertEqual(type_synergy._regret_category(20.01), "Major preview mistake")

    def test_none_when_team_of_six_is_not_a_genuine_six(self):
        self.assertIsNone(type_synergy.preview_skill(self.SIX[:5], self.SIX[:4], ["Aerodactyl"]))

    def test_none_when_actual_brought_is_not_exactly_four(self):
        self.assertIsNone(type_synergy.preview_skill(self.SIX, self.SIX[:3], ["Aerodactyl"]))

    def test_none_when_opponent_brought_is_empty(self):
        self.assertIsNone(type_synergy.preview_skill(self.SIX, self.SIX[:4], []))


if __name__ == "__main__":
    unittest.main()
