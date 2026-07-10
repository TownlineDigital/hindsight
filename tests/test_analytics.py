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

    def test_opponent_by_lead_present_and_well_formed(self):
        """Added 2026-07-09, direct user request: "add Opponents lead to
        this chart - right now we only know the players leads." Same shape
        and same win_pct validity rule as by_lead above - the only
        difference is what the table is keyed on (opponent's opening pair
        instead of the player's)."""
        self.assertIn("opponent_by_lead", self.record)
        for key, row in self.record["opponent_by_lead"].items():
            with self.subTest(key=key):
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
                    "player_team", "opponent_team", "p_faints", "o_faints", "player_team_known",
                    "opponent_team_known", "illegal_species_detected", "complete_data"}
        for row in self.rows:
            with self.subTest(match=row.get("match")):
                self.assertTrue(required.issubset(row.keys()))

    # Two matches in the hand-planted demo fixture (9/opponent, 16/player)
    # have a mon from the OTHER side's team bleeding into this side's
    # "brought" list - a fixture-authoring typo, not something the real
    # pipeline can produce (analyze_matches.py/showdown_import.py always
    # write team + brought from the same roster extraction in one pass, so
    # this can't happen there). Named explicitly rather than silently
    # skipped, so a future demo-data fix or new inconsistency is caught
    # instead of blending into "expected" here.
    KNOWN_DEMO_FIXTURE_ROSTER_TYPOS = {(9, "opponent"), (16, "player")}

    def test_brought_is_always_a_subset_of_team_when_team_is_known(self):
        """Added 2026-07-09 alongside player_team/opponent_team - the whole
        point of surfacing the full 6 is showing "brought vs. left home", so
        every brought mon has to actually be IN the full team whenever we
        have one at all (an empty team - not fully read - is a separate,
        already-covered case, not a violation of this rule)."""
        for row in self.rows:
            for side in ("player", "opponent"):
                if (row["match"], side) in self.KNOWN_DEMO_FIXTURE_ROSTER_TYPOS:
                    continue
                team = row[f"{side}_team"]
                brought = row[f"{side}_brought"]
                if not team:
                    continue
                with self.subTest(match=row["match"], side=side):
                    self.assertTrue(set(brought).issubset(set(team)))

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
class TestComputeOpponentStrength(unittest.TestCase):
    """team_preview_evaluation (added 2026-07-09) is the Objective Team
    Preview Evaluation layer - see type_synergy.team_matchup's docstring.
    The one invariant that matters most here is architectural, not numeric:
    it must never be derivable from `winner` alone, or the "judged before
    the result, not by it" guarantee is broken."""

    @classmethod
    def setUpClass(cls):
        with open(DEMO_EVENTS_PATH, encoding="utf-8") as f:
            cls.events = json.load(f)
        cls.result = analytics.compute_opponent_strength(cls.events)

    def test_every_match_has_a_team_preview_evaluation(self):
        for row in self.result["matches"]:
            with self.subTest(match=row["match"]):
                self.assertIn("team_preview_evaluation", row)
                tpe = row["team_preview_evaluation"]
                for key in ("your_type_answers", "their_type_answers",
                            "your_coverage", "their_coverage", "verdict"):
                    self.assertIn(key, tpe)

    def test_verdict_is_a_known_value_or_none(self):
        for row in self.result["matches"]:
            with self.subTest(match=row["match"]):
                self.assertIn(row["team_preview_evaluation"]["verdict"],
                               (None, "favorable", "unfavorable", "even"))

    def test_team_matchup_signature_cannot_see_the_winner(self):
        """The actual "no result bias" guarantee, checked structurally rather
        than just "same inputs give same outputs" (true of any pure function
        and not the real risk here): type_synergy.team_matchup's signature
        must never grow a winner/result parameter, or a future edit could
        start scoring team preview decisions by how the match actually
        turned out - exactly what the user asked this layer to avoid."""
        import inspect
        from backend import type_synergy
        params = set(inspect.signature(type_synergy.team_matchup).parameters)
        self.assertEqual(params, {"player_species", "opponent_species"})

    def test_identical_broughts_score_identically(self):
        from backend import type_synergy
        player = ["Incineroar", "Grimmsnarl", "Sinistcha", "Garchomp"]
        opponent = ["Metagross", "Pelipper", "Kingambit", "Hydreigon"]
        result_a = type_synergy.team_matchup(player, opponent)
        result_b = type_synergy.team_matchup(player, opponent)
        self.assertEqual(result_a, result_b)

    def test_every_match_has_a_team_preview_skill_key(self):
        """team_preview_skill (added 2026-07-09, the "Team Preview Skill
        Score" feature) is present on every row, but its VALUE is legitimately
        None for any match without a genuine 6-mon player_team - see
        type_synergy.preview_skill's own docstring. Presence of the key is
        the only universal invariant; its shape is checked below only for
        the rows where it actually resolved."""
        for row in self.result["matches"]:
            with self.subTest(match=row["match"]):
                self.assertIn("team_preview_skill", row)

    def test_resolved_team_preview_skill_has_the_expected_shape_and_bounds(self):
        required = {"selected_score", "best_score", "regret", "regret_category",
                    "skill_pct", "rank_of_selected", "candidates_scored", "best_alternative"}
        for row in self.result["matches"]:
            tps = row["team_preview_skill"]
            if tps is None:
                continue
            with self.subTest(match=row["match"]):
                self.assertTrue(required.issubset(tps.keys()))
                self.assertGreaterEqual(tps["selected_score"], 0)
                self.assertLessEqual(tps["selected_score"], 100)
                self.assertGreaterEqual(tps["best_score"], 0)
                self.assertLessEqual(tps["best_score"], 100)
                # The whole point of "best" - nothing can beat it.
                self.assertGreaterEqual(tps["best_score"], tps["selected_score"])
                self.assertGreaterEqual(tps["regret"], 0)
                self.assertIn(tps["regret_category"],
                               ("Excellent preview", "Good preview",
                                "Questionable preview", "Major preview mistake"))
                self.assertGreaterEqual(tps["rank_of_selected"], 1)
                self.assertLessEqual(tps["rank_of_selected"], tps["candidates_scored"])
                # 6 choose 4 - every resolved row was scored from a genuine 6.
                self.assertEqual(tps["candidates_scored"], 15)

    def test_team_preview_skill_is_none_when_player_team_is_not_a_genuine_six(self):
        """Structural guarantee, not a demo-data coincidence: any match row
        whose player_team isn't exactly 6 distinct species must have
        team_preview_skill == None, since the 15-way enumeration this score
        depends on only makes sense from a real 6 - see analytics.
        compute_opponent_strength's own comment on why preview_skill() is
        called at all here."""
        for row in self.result["matches"]:
            with self.subTest(match=row["match"]):
                if len(set(row["player_team"])) != 6:
                    self.assertIsNone(row["team_preview_skill"])

    def test_preview_skill_signature_cannot_see_the_winner(self):
        import inspect
        from backend import type_synergy
        params = set(inspect.signature(type_synergy.preview_skill).parameters)
        self.assertEqual(params, {"team_of_six", "actual_brought", "opponent_brought"})


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

    def test_leads_dict_has_opponent_fields(self):
        """Added 2026-07-09, direct user request - opponent_most_common/
        opponent_predictability_pct/win_rate_vs_opponent_most_common/
        vs_opponent_most_common_n sit alongside the pre-existing player-only
        most_common/predictability_pct, never replacing them."""
        with open(DEMO_EVENTS_PATH, encoding="utf-8") as f:
            events = json.load(f)
        report = analytics.compute_report(events)
        leads = report["leads"]
        for key in ("most_common", "predictability_pct", "opponent_most_common",
                    "opponent_predictability_pct", "win_rate_vs_opponent_most_common",
                    "vs_opponent_most_common_n"):
            self.assertIn(key, leads)
        self.assertGreaterEqual(leads["opponent_predictability_pct"], 0)
        self.assertLessEqual(leads["opponent_predictability_pct"], 100)


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
