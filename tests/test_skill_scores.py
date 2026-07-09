"""
Behavior tests for skill_scores.py's compute_skill_scores(). These are
deliberately BEHAVIOR assertions (a dominant team should score higher on
tempo than a struggling one) rather than hardcoded magic numbers - the 0-100
scalings are explicitly documented as "heuristic anchors... recalibrate once
enough users exist" (see skill_scores.py's own module docstring), so pinning
exact values here would make this test suite fight every future
recalibration instead of catching real regressions.

Run: py -m unittest tests.test_skill_scores -v   (from poc-starter/)
"""

import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import skill_scores as ss  # noqa: E402


def _match(idx, winner, player_lead, player_brought, p_faints, o_faints, first_ko="player"):
    """Build the minimal event list compute_skill_scores() actually reads for
    one match: a team_preview (lead/brought) + enough pokemon_fainted events
    to reflect the KO sequence + a battle_end with the winner."""
    events = [{
        "event": "team_preview", "match": idx, "timestamp": 0,
        "player_lead": player_lead, "player_brought": player_brought,
    }]
    ts = 1
    # Interleave faints so first_ko controls who draws first blood, and the
    # final faint count matches p_faints/o_faints exactly.
    sides = []
    if first_ko == "player":
        sides = ["opponent"] * o_faints + ["player"] * p_faints
    else:
        sides = ["player"] * p_faints + ["opponent"] * o_faints
    for side in sides:
        events.append({"event": "pokemon_fainted", "actor": side, "match": idx, "timestamp": ts})
        ts += 1
    events.append({"event": "battle_end", "match": idx, "timestamp": ts, "winner": winner})
    return events


class TestComputeSkillScores(unittest.TestCase):

    def test_no_decided_matches_returns_none(self):
        self.assertIsNone(ss.compute_skill_scores([]))

    def test_dominant_record_scores_higher_tempo_than_struggling_record(self):
        """Dominant: always draws first blood and wins with a big KO
        differential. Struggling: opponent draws first blood and wins are
        narrow/rare. Tempo should clearly separate the two."""
        dominant = []
        for i in range(1, 11):
            dominant += _match(i, "player", ["Charizard", "Whimsicott"], ["Charizard", "Whimsicott", "Garchomp", "Grimmsnarl"],
                                p_faints=0, o_faints=4, first_ko="player")
        struggling = []
        for i in range(1, 11):
            struggling += _match(i, "opponent", ["Charizard", "Whimsicott"], ["Charizard", "Whimsicott", "Garchomp", "Grimmsnarl"],
                                  p_faints=4, o_faints=1, first_ko="opponent")

        dominant_scores = ss.compute_skill_scores(dominant)
        struggling_scores = ss.compute_skill_scores(struggling)
        self.assertGreater(dominant_scores["scores"]["tempo"], struggling_scores["scores"]["tempo"])

    def test_varied_leads_score_higher_adaptability_than_a_single_repeated_lead(self):
        varied = []
        leads = [["Charizard", "Whimsicott"], ["Garchomp", "Grimmsnarl"], ["Sceptile", "Metagross"],
                 ["Mawile", "Overqwil"], ["Dragalge", "Musharna"]]
        for i in range(1, 11):
            varied += _match(i, "player", leads[i % len(leads)], ["Charizard", "Whimsicott", "Garchomp", "Grimmsnarl"],
                              p_faints=1, o_faints=4, first_ko="player")

        repetitive = []
        for i in range(1, 11):
            repetitive += _match(i, "player", ["Charizard", "Whimsicott"], ["Charizard", "Whimsicott", "Garchomp", "Grimmsnarl"],
                                  p_faints=1, o_faints=4, first_ko="player")

        varied_scores = ss.compute_skill_scores(varied)
        repetitive_scores = ss.compute_skill_scores(repetitive)
        self.assertGreater(varied_scores["scores"]["adaptability"], repetitive_scores["scores"]["adaptability"])

    def test_confidence_tier_matches_documented_thresholds(self):
        """<25 provisional, 25 good, 50 strong, 100 exceptional - per the
        module docstring and tier()'s own thresholds."""
        self.assertEqual(ss.tier(10)[0], "Provisional (building)")
        self.assertEqual(ss.tier(25)[0], "Good understanding")
        self.assertEqual(ss.tier(50)[0], "Strong")
        self.assertEqual(ss.tier(100)[0], "Exceptional")

    def test_overall_is_average_of_the_four_scores(self):
        events = []
        for i in range(1, 6):
            events += _match(i, "player", ["Charizard", "Whimsicott"], ["Charizard", "Whimsicott", "Garchomp", "Grimmsnarl"],
                              p_faints=1, o_faints=4, first_ko="player")
        result = ss.compute_skill_scores(events)
        expected = round(sum(result["scores"].values()) / 4, 1)
        self.assertEqual(result["overall"], expected)


if __name__ == "__main__":
    unittest.main()
