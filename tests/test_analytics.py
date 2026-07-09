"""
Regression tests for backend/analytics.py, run against the REAL seeded demo
job (jobs/demo/events.json) rather than synthetic fixtures where practical -
this is the actual data every dashboard endpoint serves today, so testing
against it catches "my last edit broke a real endpoint" the same way loading
the dashboard would, just without needing the server running.

These are mostly INVARIANT checks (things that must always be true of any
valid output) rather than hardcoded magic numbers, because the underlying
demo data can legitimately change (e.g. after re-running --only on flagged
matches) - a test asserting "win_rate == 63.6" would break on every accuracy
fix even though nothing is actually wrong. Assert the shape and the rules,
not today's specific numbers.

Run: py -m unittest tests.test_analytics -v   (from poc-starter/)
"""

import json
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend import analytics  # noqa: E402

DEMO_EVENTS_PATH = os.path.join(BASE_DIR, "jobs", "demo", "events.json")
DEMO_SCHEMA_PATH = os.path.join(BASE_DIR, "jobs", "demo", "schema.json")


@unittest.skipUnless(os.path.exists(DEMO_EVENTS_PATH),
                      f"No seeded demo job at {DEMO_EVENTS_PATH} - run seed_demo_job.py first")
class TestComputeRecord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DEMO_EVENTS_PATH, encoding="utf-8") as f:
            cls.events = json.load(f)
        cls.record = analytics.compute_record(cls.events)

    def test_wins_plus_losses_equals_matches(self):
        self.assertEqual(self.record["wins"] + self.record["losses"], self.record["matches"])

    def test_win_rate_is_a_valid_percentage(self):
        self.assertGreaterEqual(self.record["win_rate"], 0)
        self.assertLessEqual(self.record["win_rate"], 100)

    def test_total_games_covers_undetermined_plus_decided(self):
        self.assertEqual(self.record["total_games"], self.record["matches"] + self.record["undetermined"])

    def test_by_lead_and_by_bring_win_pcts_are_valid(self):
        for table_name in ("by_lead", "by_bring"):
            table = self.record[table_name]
            for key, row in table.items():
                with self.subTest(table=table_name, key=key):
                    self.assertEqual(row["total"], row["wins"] + (row["total"] - row["wins"]))
                    self.assertGreaterEqual(row["win_pct"], 0)
                    self.assertLessEqual(row["win_pct"], 100)


@unittest.skipUnless(os.path.exists(DEMO_EVENTS_PATH), "No seeded demo job")
class TestComputeMatchList(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DEMO_EVENTS_PATH, encoding="utf-8") as f:
            cls.events = json.load(f)
        cls.rows = analytics.compute_match_list(cls.events)

    def test_every_row_has_required_fields(self):
        required = {"match", "winner", "player_lead", "player_brought", "opponent_brought",
                    "p_faints", "o_faints", "player_team_known", "opponent_team_known",
                    "illegal_species_detected", "complete_data"}
        for row in self.rows:
            with self.subTest(match=row.get("match")):
                self.assertTrue(required.issubset(row.keys()))

    def test_complete_data_requires_player_team_known_and_no_illegal_species(self):
        """This is the exact rule the dashboard's ⚠/🚫 flags depend on - only
        OUR team needs to be fully known, the opponent's partial reveal is
        expected and doesn't count against completeness."""
        for row in self.rows:
            with self.subTest(match=row["match"]):
                expected = row["player_team_known"] and not row["illegal_species_detected"]
                self.assertEqual(row["complete_data"], expected)

    def test_player_team_known_means_at_least_4_brought(self):
        for row in self.rows:
            with self.subTest(match=row["match"]):
                if row["player_team_known"]:
                    self.assertGreaterEqual(len(row["player_brought"]), 4)


@unittest.skipUnless(os.path.exists(DEMO_EVENTS_PATH), "No seeded demo job")
class TestComputeReport(unittest.TestCase):
    def test_tera_stats_are_none_when_format_disallows_tera(self):
        """Regression test for the fake-100%-Tera-win-rate bug - Pokemon
        Champions doesn't have Terastallization, so this must be None, not a
        fabricated 0%/100%."""
        with open(DEMO_EVENTS_PATH, encoding="utf-8") as f:
            events = json.load(f)
        rules = {"terastallization": False}
        report = analytics.compute_report(events, rules=rules)
        self.assertIsNone(report["tera"])

    def test_tera_stats_present_when_format_allows_tera(self):
        with open(DEMO_EVENTS_PATH, encoding="utf-8") as f:
            events = json.load(f)
        report = analytics.compute_report(events, rules={"terastallization": True})
        self.assertIsNotNone(report["tera"])

    def test_flags_list_is_never_empty(self):
        """compute_report always returns at least a "not enough data yet"
        placeholder flag rather than an empty list - the dashboard always
        has something to show in the Coaching Flags section."""
        with open(DEMO_EVENTS_PATH, encoding="utf-8") as f:
            events = json.load(f)
        report = analytics.compute_report(events)
        self.assertGreater(len(report["flags"]), 0)


@unittest.skipUnless(os.path.exists(DEMO_EVENTS_PATH), "No seeded demo job")
class TestComputeSkillScores(unittest.TestCase):
    def test_all_four_scores_in_0_100_range(self):
        with open(DEMO_EVENTS_PATH, encoding="utf-8") as f:
            events = json.load(f)
        result = analytics.compute_skill_scores(events)
        self.assertIsNotNone(result["scores"])
        for key, value in result["scores"].items():
            with self.subTest(score=key):
                self.assertGreaterEqual(value, 0)
                self.assertLessEqual(value, 100)

    def test_no_decided_matches_returns_placeholder_not_a_crash(self):
        result = analytics.compute_skill_scores([])
        self.assertEqual(result["matches_analyzed"], 0)
        self.assertIsNone(result["overall"])


@unittest.skipUnless(os.path.exists(DEMO_EVENTS_PATH), "No seeded demo job")
class TestComputeDecisionWindows(unittest.TestCase):
    """See decision_windows.py's own test suite (tests/test_decision_windows.py)
    for the detailed behavior coverage - these are just the invariants the
    real seeded demo job must satisfy, the same "run against real data,
    check the shape/rules rather than magic numbers" convention as the
    classes above. The demo job is hand-planted placeholder data (not real
    pipeline output) and may or may not have field_state/turn events at all,
    so this doesn't assume any particular number of windows come back -
    empty is a valid, correct result (see decision_windows.py's docstring)."""

    def test_returns_a_list_without_crashing(self):
        with open(DEMO_EVENTS_PATH, encoding="utf-8") as f:
            events = json.load(f)
        result = analytics.compute_decision_windows(events)
        self.assertIsInstance(result, list)

    def test_every_window_has_the_expected_shape(self):
        with open(DEMO_EVENTS_PATH, encoding="utf-8") as f:
            events = json.load(f)
        result = analytics.compute_decision_windows(events)
        for window in result:
            with self.subTest(match=window.get("match"), turn=window.get("turn")):
                self.assertIn("turn", window)
                self.assertIn("match", window)
                for side in ("player", "opponent"):
                    self.assertIn(side, window)
                    for key in ("board", "available_pokemon", "switch_options",
                                "known_moves", "chosen_actions"):
                        self.assertIn(key, window[side])

    def test_empty_events_returns_empty_list(self):
        self.assertEqual(analytics.compute_decision_windows([]), [])


@unittest.skipUnless(os.path.exists(DEMO_EVENTS_PATH), "No seeded demo job")
class TestComputeStrategicAnalysis(unittest.TestCase):
    """See strategic_analysis.py's own test suite (tests/test_strategic_analysis.py)
    for the detailed behavior coverage (including a real-replay integration
    test) - these are just the invariants the real seeded demo job must
    satisfy, same "run against real data, check shape/rules not magic
    numbers" convention as TestComputeDecisionWindows above. The demo job
    may or may not have field_state/turn events, so an empty
    momentum_timeline per match is a valid, correct result (inherited
    from decision_windows.py - see strategic_analysis.py's docstring)."""

    def test_returns_a_list_without_crashing(self):
        with open(DEMO_EVENTS_PATH, encoding="utf-8") as f:
            events = json.load(f)
        result = analytics.compute_strategic_analysis(events)
        self.assertIsInstance(result, list)

    def test_every_match_entry_has_the_expected_shape(self):
        with open(DEMO_EVENTS_PATH, encoding="utf-8") as f:
            events = json.load(f)
        result = analytics.compute_strategic_analysis(events)
        for entry in result:
            with self.subTest(match=entry.get("match")):
                self.assertIn("match", entry)
                self.assertIn("momentum_timeline", entry)
                self.assertIn("resource_summary", entry)
                self.assertIn("mistake_candidates", entry)
                for turn in entry["momentum_timeline"]:
                    for key in ("turn", "player_alive", "opponent_alive", "score",
                                "delta", "win_probability", "reasons"):
                        self.assertIn(key, turn)

    def test_win_probability_always_in_valid_range(self):
        with open(DEMO_EVENTS_PATH, encoding="utf-8") as f:
            events = json.load(f)
        result = analytics.compute_strategic_analysis(events)
        for entry in result:
            for turn in entry["momentum_timeline"]:
                with self.subTest(match=entry["match"], turn=turn["turn"]):
                    self.assertGreater(turn["win_probability"], 0.0)
                    self.assertLess(turn["win_probability"], 100.0)

    def test_empty_events_returns_empty_list(self):
        self.assertEqual(analytics.compute_strategic_analysis([]), [])


if __name__ == "__main__":
    unittest.main()
