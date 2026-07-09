"""
Tests for backend/type_synergy.py's team_matchup() - the Objective Team
Preview Evaluation heuristic added 2026-07-09 (direct user request: "what
pokemon we both brought and how it was advantageous or disadvantageous to
us"). Uses hand-picked species with well-known type relationships rather than
real match data, so the expected answers are checkable by hand against
pokedex.TYPE_CHART.

Run: py -m unittest tests.test_type_synergy -v   (from poc-starter/)
"""

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


if __name__ == "__main__":
    unittest.main()
