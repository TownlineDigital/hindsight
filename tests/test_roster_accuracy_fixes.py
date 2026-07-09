"""
Regression tests for accuracy fixes made after TWO rounds of a real user
benchmark comparison (job 8c10092ac4a9's manual match notes vs. the
pipeline's own events.json). The player's own roster/brought/leads/winner
were correct in all 5 matches both rounds; the opponent-side roster read
was the entire source of error, and a full re-run after round 1's fixes
showed BOTH real improvements and a same-match regression (plain model
non-determinism) - which is exactly what motivated round 2's fixes below.

Round 1 (still covered here):
1. read_roster()'s sparsity metric (_roster_sparsity) is keyed on the WORSE
   of the two sides, not player_team alone.
2. summarize_roster_conflicts() rolls up per-event roster_conflict flags
   into a match-level "likely_missed_opponent_species" signal.
(OPPONENT_COLUMN_ZOOM/CROP_CAP bumps are plain constants already covered by
tests/test_opponent_column_crop.py, which reads its expected dimensions
from the constants themselves.)

Round 2 (added this pass):
3. apply_likely_missed_species_correction() folds that "likely missed"
   signal directly INTO opponent_team/opponent_brought, instead of leaving
   them wrong next to a note about it.
4. reconcile_player_rosters_across_matches() catches a single match whose
   player_team disagrees with every other match's unanimous read (job
   8c10092ac4a9's match 3 side-mixup case) and corrects just that outlier.
5. read_roster() no longer stops at the first attempt that merely looks
   "good enough" (_roster_sparsity is no longer a stopping gate at all) -
   it now always runs every ROSTER_SEARCH_ATTEMPTS window and merges them
   (_merge_roster_reads), since a single sample was shown to sometimes be
   WORSE even when it looked complete (match 2's Kingambit->Heracross
   misread happened with a "full" 6/6 opponent_team; match 4 regressed
   between two full runs of the same video from model non-determinism
   alone).

Run: py -m unittest tests.test_roster_accuracy_fixes -v   (from poc-starter/)
"""

import unittest
from unittest.mock import patch

import analyze_matches as am


class TestRosterSparsity(unittest.TestCase):

    def test_empty_roster_is_zero_on_all_fronts(self):
        self.assertEqual(am._roster_sparsity({}), (0, 0, 0))

    def test_keyed_on_the_worse_side_not_player_alone(self):
        roster = {"player_team": ["A", "B", "C", "D", "E", "F"], "opponent_team": ["X"]}
        worst, pteam_n, oteam_n = am._roster_sparsity(roster)
        self.assertEqual(worst, 1)   # min(6, 1), not 6
        self.assertEqual(pteam_n, 6)
        self.assertEqual(oteam_n, 1)

    def test_missing_keys_treated_as_empty(self):
        self.assertEqual(am._roster_sparsity({"player_team": ["A"]}), (0, 1, 0))


class TestMergeRosterReads(unittest.TestCase):

    def test_unions_team_lists_deduped(self):
        a = {"player_team": ["Incineroar", "Grimmsnarl"], "opponent_team": ["Raichu"]}
        b = {"player_team": ["Grimmsnarl", "Staraptor"], "opponent_team": ["Dragapult", "Raichu"]}
        merged = am._merge_roster_reads(a, b, team_size=6)
        self.assertEqual(merged["player_team"], ["Incineroar", "Grimmsnarl", "Staraptor"])
        self.assertEqual(merged["opponent_team"], ["Raichu", "Dragapult"])

    def test_mega_and_regional_variants_not_duplicated(self):
        a = {"player_team": ["Mawile"], "opponent_team": []}
        b = {"player_team": ["Mawile (Mega)"], "opponent_team": []}
        merged = am._merge_roster_reads(a, b)
        self.assertEqual(merged["player_team"], ["Mawile"])

    def test_capped_at_team_size(self):
        a = {"player_team": ["A", "B", "C"], "opponent_team": []}
        b = {"player_team": ["D", "E", "F", "G", "H"], "opponent_team": []}
        merged = am._merge_roster_reads(a, b, team_size=4)
        self.assertEqual(merged["player_team"], ["A", "B", "C", "D"])

    def test_brought_prefers_a_then_falls_back_to_b(self):
        a = {"player_team": [], "opponent_team": [], "player_brought": ["X", "Y"]}
        b = {"player_team": [], "opponent_team": [], "player_brought": ["Z"]}
        self.assertEqual(am._merge_roster_reads(a, b)["player_brought"], ["X", "Y"])
        c = {"player_team": [], "opponent_team": [], "player_brought": []}
        self.assertEqual(am._merge_roster_reads(c, b)["player_brought"], ["Z"])


class TestReadRosterAlwaysMergesBothAttempts(unittest.TestCase):
    """Exercises read_roster() end-to-end with sample_window/
    crop_opponent_icon_column/call_with_fallback all mocked out, so these
    run instantly with no real ffmpeg/Gemini calls."""

    def _run(self, attempt_results, rules=None):
        """attempt_results: list of roster dicts, one per call. Cycled with
        modulo rather than indexed 1:1 against ROSTER_SEARCH_ATTEMPTS - that
        list's length is a real, evolving tuning knob (bumped 2 -> 5
        attempts 2026-07-07, see its own comment), not something these
        tests should hardcode; a short attempt_results list (e.g. 2 entries)
        just repeats for any later attempts, which is harmless for these
        tests (merging duplicate reads is a no-op via _merge_roster_reads'
        own dedup) and keeps the fixture decoupled from that constant's
        exact length. Returns (roster, had_failure)."""
        calls = {"n": 0}

        def fake_sample_window(*a, **kw):
            return [("fake_frame.jpg", 0.0)]   # non-empty so the attempt isn't skipped

        def fake_crop(*a, **kw):
            return []

        def fake_call_with_fallback(client, hard, cheap, prompt, paths):
            i = calls["n"] % len(attempt_results)
            calls["n"] += 1
            return attempt_results[i]

        with patch.object(am, "sample_window", fake_sample_window), \
             patch.object(am, "crop_opponent_icon_column", fake_crop), \
             patch.object(am, "call_with_fallback", fake_call_with_fallback):
            return am.read_roster(None, "model", "model", "ffmpeg", "video.mp4", 100, "workdir", "", rules=rules)

    def test_both_attempts_are_always_made_and_merged(self):
        """The core round-2 fix: even though attempt 1 already looks
        complete, attempt 2 must still run, and anything new it finds gets
        merged in - this is what would have caught match 2's
        Kingambit misread if a second attempt happened to name it."""
        full_but_wrong = {"player_team": ["A", "B", "C", "D", "E", "F"],
                          "opponent_team": ["W", "X", "Y", "Z", "P", "Q"]}
        second_finds_more = {"player_team": ["A", "B", "C", "D", "E", "F"],
                             "opponent_team": ["W", "X", "Y", "Z", "P", "NEW_SPECIES"]}
        roster, had_failure = self._run([full_but_wrong, second_finds_more], rules={"team_size": 7})
        self.assertIn("NEW_SPECIES", roster["opponent_team"])
        self.assertFalse(had_failure)

    def test_falls_back_gracefully_when_only_one_attempt_has_frames(self):
        """If one attempt's sample_window comes back empty (e.g. too close
        to the start of the video), the other attempt's read is still used
        - not treated as total failure."""
        only_result = {"player_team": ["A", "B"], "opponent_team": ["X"]}

        call_n = {"n": 0}

        def fake_sample_window(*a, **kw):
            call_n["n"] += 1
            if call_n["n"] == 1:
                return []   # attempt 1: no frames at all
            return [("fake_frame.jpg", 0.0)]

        def fake_crop(*a, **kw):
            return []

        def fake_call(client, hard, cheap, prompt, paths):
            return only_result

        with patch.object(am, "sample_window", fake_sample_window), \
             patch.object(am, "crop_opponent_icon_column", fake_crop), \
             patch.object(am, "call_with_fallback", fake_call):
            roster, had_failure = am.read_roster(None, "model", "model", "ffmpeg", "video.mp4", 100, "workdir", "")
        self.assertEqual(roster["player_team"], ["A", "B"])
        self.assertFalse(had_failure)

    def test_no_frames_at_all_returns_empty_roster(self):
        def fake_sample_window(*a, **kw):
            return []

        with patch.object(am, "sample_window", fake_sample_window):
            roster, had_failure = am.read_roster(None, "model", "model", "ffmpeg", "video.mp4", 100, "workdir", "")
        self.assertEqual(roster, {})
        self.assertFalse(had_failure)

    def test_exception_on_one_attempt_still_merges_with_the_other(self):
        good = {"player_team": ["A", "B"], "opponent_team": ["X", "Y"]}
        call_n = {"n": 0}

        def fake_sample_window(*a, **kw):
            return [("fake_frame.jpg", 0.0)]

        def fake_crop(*a, **kw):
            return []

        def flaky_call(client, hard, cheap, prompt, paths):
            call_n["n"] += 1
            if call_n["n"] == 1:
                raise RuntimeError("simulated API error")
            return good

        with patch.object(am, "sample_window", fake_sample_window), \
             patch.object(am, "crop_opponent_icon_column", fake_crop), \
             patch.object(am, "call_with_fallback", flaky_call):
            roster, had_failure = am.read_roster(None, "model", "model", "ffmpeg", "video.mp4", 100, "workdir", "")
        self.assertTrue(had_failure)
        self.assertEqual(roster["player_team"], ["A", "B"])

    def test_exception_on_every_attempt_returns_empty_roster(self):
        def fake_sample_window(*a, **kw):
            return [("fake_frame.jpg", 0.0)]

        def fake_crop(*a, **kw):
            return []

        def always_raises(*a, **kw):
            raise RuntimeError("simulated API error")

        with patch.object(am, "sample_window", fake_sample_window), \
             patch.object(am, "crop_opponent_icon_column", fake_crop), \
             patch.object(am, "call_with_fallback", always_raises):
            roster, had_failure = am.read_roster(None, "model", "model", "ffmpeg", "video.mp4", 100, "workdir", "")
        self.assertTrue(had_failure)
        self.assertEqual(roster, {"player_team": [], "opponent_team": [], "player_brought": [], "opponent_brought": []})


class TestSummarizeRosterConflicts(unittest.TestCase):

    def _event(self, roster_conflict_species=None, actor="opponent"):
        # actor defaults to "opponent" since summarize_roster_conflicts (fixed
        # 2026-07-07, see its own docstring) only rolls up opponent-side
        # conflicts - a player-side conflict is a real, separate problem it
        # deliberately does not fold into this OPPONENT-side signal.
        e = {"event": "move_used", "match": 1, "actor": actor}
        if roster_conflict_species is not None:
            e["roster_conflict"] = True
            e["roster_conflict_species"] = roster_conflict_species
        return e

    def test_player_side_conflict_is_not_rolled_up(self):
        """Real bug found 2026-07-07 (job 8c10092ac4a9, match 3): a PLAYER-side
        misread ("Drampa", actor="player") recurring twice used to get counted
        the same as an opponent-side conflict and wrongly injected into the
        opponent's roster. Only actor="opponent" conflicts should count."""
        tp = {"event": "team_preview", "match": 1}
        events = [
            self._event(["Drampa"], actor="player"),
            self._event(["Drampa"], actor="player"),
        ]
        am.summarize_roster_conflicts(events, tp)
        self.assertNotIn("likely_missed_opponent_species", tp)

    def test_no_conflicts_leaves_team_preview_unchanged(self):
        tp = {"event": "team_preview", "match": 1}
        events = [self._event(), self._event()]
        am.summarize_roster_conflicts(events, tp)
        self.assertNotIn("likely_missed_opponent_species", tp)

    def test_single_one_off_conflict_is_not_enough(self):
        tp = {"event": "team_preview", "match": 1}
        events = [self._event(["Dragalge"]), self._event()]
        am.summarize_roster_conflicts(events, tp)
        self.assertNotIn("likely_missed_opponent_species", tp)

    def test_recurring_species_surfaces_on_team_preview(self):
        tp = {"event": "team_preview", "match": 1}
        events = [self._event(["Dragalge"]), self._event(["Dragalge"]), self._event()]
        am.summarize_roster_conflicts(events, tp)
        self.assertEqual(tp["likely_missed_opponent_species"], ["Dragalge"])

    def test_species_normalized_across_mega_and_form_variants_still_count_together(self):
        tp = {"event": "team_preview", "match": 1}
        events = [self._event(["Mawile"]), self._event(["Mawile (Mega)"])]
        am.summarize_roster_conflicts(events, tp)
        self.assertEqual(tp["likely_missed_opponent_species"], ["Mawile"])

    def test_multiple_recurring_species_both_listed_sorted(self):
        tp = {"event": "team_preview", "match": 1}
        events = [
            self._event(["Dragalge"]), self._event(["Dragalge"]),
            self._event(["Qwilfish"]), self._event(["Qwilfish"]),
            self._event(["Latias"]),
        ]
        am.summarize_roster_conflicts(events, tp)
        self.assertEqual(tp["likely_missed_opponent_species"], ["Dragalge", "Qwilfish"])

    def test_custom_min_occurrences_respected(self):
        tp = {"event": "team_preview", "match": 1}
        events = [self._event(["Dragalge"])]
        am.summarize_roster_conflicts(events, tp, min_occurrences=1)
        self.assertEqual(tp["likely_missed_opponent_species"], ["Dragalge"])


class TestApplyLikelyMissedSpeciesCorrection(unittest.TestCase):

    def test_noop_when_no_flag_present(self):
        tp = {"opponent_team": "Raichu, Dragapult", "opponent_brought": "Raichu"}
        am.apply_likely_missed_species_correction(tp)
        self.assertEqual(tp["opponent_team"], "Raichu, Dragapult")
        self.assertEqual(tp["opponent_brought"], "Raichu")

    def test_appends_missed_species_into_team_and_brought(self):
        """The real job 8c10092ac4a9 match 5 case: Dragalge was flagged as
        likely-missed but the roster itself stayed wrong until this ran."""
        tp = {
            "opponent_team": "Raichu, Dragapult, Empoleon, Mimikyu",
            "opponent_brought": "Dragapult, Empoleon, Raichu",
            "likely_missed_opponent_species": ["Dragalge"],
        }
        am.apply_likely_missed_species_correction(tp)
        self.assertIn("Dragalge", tp["opponent_team"])
        self.assertIn("Dragalge", tp["opponent_brought"])

    def test_does_not_duplicate_species_already_present(self):
        tp = {
            "opponent_team": "Raichu, Dragalge",
            "opponent_brought": "Raichu, Dragalge",
            "likely_missed_opponent_species": ["Dragalge"],
        }
        am.apply_likely_missed_species_correction(tp)
        self.assertEqual(tp["opponent_team"].count("Dragalge"), 1)
        self.assertEqual(tp["opponent_brought"].count("Dragalge"), 1)

    def test_respects_bring_cap(self):
        tp = {
            "opponent_team": "A, B, C, D",
            "opponent_brought": "A, B, C, D",   # already at the cap
            "likely_missed_opponent_species": ["E"],
        }
        am.apply_likely_missed_species_correction(tp, opponent_bring_cap=4)
        self.assertIn("E", tp["opponent_team"])          # team not yet at its own cap (6)
        self.assertNotIn("E", tp["opponent_brought"])    # brought is

    def test_mega_variant_already_present_is_not_duplicated(self):
        tp = {
            "opponent_team": "Mawile",
            "opponent_brought": "Mawile",
            "likely_missed_opponent_species": ["Mawile (Mega)"],
        }
        am.apply_likely_missed_species_correction(tp)
        self.assertEqual(tp["opponent_team"], "Mawile")

    def test_respects_opponent_team_cap_default_6(self):
        """The real found bug (2026-07-08): with no cap at all, a species
        seen fighting but missing from an already-full 6-member roster read
        used to get appended unconditionally, producing an impossible
        7-member opponent_team (matches 3, 10, 12 of a real 10-match
        production run). Species Clause caps a real team at 6."""
        tp = {
            "opponent_team": "A, B, C, D, E, F",   # already 6/6
            "opponent_brought": "A, B",
            "likely_missed_opponent_species": ["G"],
        }
        am.apply_likely_missed_species_correction(tp)
        self.assertEqual(tp["opponent_team"], "A, B, C, D, E, F")   # untouched, NOT 7 entries
        self.assertEqual(tp["opponent_team"].split(", ").__len__(), 6)

    def test_species_that_cant_fit_recorded_in_likely_missed_but_team_full(self):
        tp = {
            "opponent_team": "A, B, C, D, E, F",
            "opponent_brought": "A, B",
            "likely_missed_opponent_species": ["G"],
        }
        am.apply_likely_missed_species_correction(tp)
        self.assertEqual(tp["likely_missed_but_team_full"], ["G"])

    def test_no_likely_missed_but_team_full_field_when_team_has_room(self):
        """The field should only appear when something genuinely couldn't
        fit - a normal, successful correction shouldn't grow a new field
        that downstream code has to learn to ignore."""
        tp = {
            "opponent_team": "A, B, C",
            "opponent_brought": "A, B",
            "likely_missed_opponent_species": ["G"],
        }
        am.apply_likely_missed_species_correction(tp)
        self.assertNotIn("likely_missed_but_team_full", tp)

    def test_duplicate_species_still_eligible_for_brought_even_when_team_full(self):
        """A species already present in a full opponent_team is a duplicate,
        not a genuinely new 7th member - it should still be able to be
        folded into opponent_brought (it's not blocked by the team cap,
        which only limits growing the TEAM list past 6)."""
        tp = {
            "opponent_team": "A, B, C, D, E, Dragalge",   # already 6/6, Dragalge present
            "opponent_brought": "A, B",
            "likely_missed_opponent_species": ["Dragalge"],
        }
        am.apply_likely_missed_species_correction(tp)
        self.assertEqual(tp["opponent_team"], "A, B, C, D, E, Dragalge")   # unchanged, still 6
        self.assertIn("Dragalge", tp["opponent_brought"])
        self.assertNotIn("likely_missed_but_team_full", tp)   # it fit fine, wasn't blocked

    def test_custom_opponent_team_cap_respected(self):
        """Singles jobs (or any format whose rules.team_size differs from 6)
        pass their own team_size through as opponent_team_cap - e.g. a
        3-member Singles team should cap at 3, not the doubles default."""
        tp = {
            "opponent_team": "A, B, C",
            "opponent_brought": "",
            "likely_missed_opponent_species": ["D"],
        }
        am.apply_likely_missed_species_correction(tp, opponent_team_cap=3)
        self.assertEqual(tp["opponent_team"], "A, B, C")
        self.assertEqual(tp["likely_missed_but_team_full"], ["D"])

    def test_multiple_missed_species_some_fit_some_dont(self):
        tp = {
            "opponent_team": "A, B, C, D, E",   # 5/6, room for exactly one more
            "opponent_brought": "A, B",
            "likely_missed_opponent_species": ["F", "G"],
        }
        am.apply_likely_missed_species_correction(tp)
        team_list = tp["opponent_team"].split(", ")
        self.assertEqual(len(team_list), 6)
        self.assertIn("F", team_list)
        self.assertNotIn("G", team_list)
        self.assertEqual(tp["likely_missed_but_team_full"], ["G"])


class TestReconcilePlayerRostersAcrossMatches(unittest.TestCase):

    def _tp(self, match, player_team):
        return {"event": "team_preview", "match": match, "player_team": player_team}

    def test_below_min_matches_does_nothing(self):
        events = [self._tp(1, "A, B"), self._tp(2, "X, Y")]
        am.reconcile_player_rosters_across_matches(events, min_matches=3)
        self.assertEqual(events[1]["player_team"], "X, Y")
        self.assertNotIn("player_team_corrected_by_cross_match_consistency", events[1])

    def test_single_outlier_corrected_to_unanimous_majority(self):
        """The real job 8c10092ac4a9 match 3 case: 4 matches agree, one
        (the outlier) reads a badly different, partly-mixed-up team."""
        real_team = "Incineroar, Grimmsnarl, Sinistcha, Drampa, Serperior, Staraptor"
        events = [
            self._tp(1, real_team), self._tp(2, real_team),
            self._tp(3, "Arcanine, Grimmsnarl, Pelipper, Staraptor, Sinistcha"),
            self._tp(4, real_team), self._tp(5, real_team),
        ]
        am.reconcile_player_rosters_across_matches(events)
        outlier = events[2]
        self.assertEqual(outlier["player_team"], real_team)
        self.assertEqual(outlier["player_team_original_read"],
                         "Arcanine, Grimmsnarl, Pelipper, Staraptor, Sinistcha")
        self.assertTrue(outlier["player_team_corrected_by_cross_match_consistency"])
        # Everyone else untouched
        for e in (events[0], events[1], events[3], events[4]):
            self.assertNotIn("player_team_corrected_by_cross_match_consistency", e)

    def test_two_different_outliers_are_not_corrected(self):
        """Ambiguous case - two matches disagree with the majority in
        DIFFERENT ways. Too uncertain to guess which (if either) is right,
        so neither gets touched."""
        real_team = "A, B, C, D, E, F"
        events = [
            self._tp(1, real_team), self._tp(2, real_team), self._tp(3, real_team),
            self._tp(4, "X, Y, Z"),
            self._tp(5, "P, Q, R"),
        ]
        am.reconcile_player_rosters_across_matches(events)
        self.assertNotIn("player_team_corrected_by_cross_match_consistency", events[3])
        self.assertNotIn("player_team_corrected_by_cross_match_consistency", events[4])

    def test_unanimous_agreement_leaves_everything_untouched(self):
        real_team = "A, B, C, D, E, F"
        events = [self._tp(i, real_team) for i in range(1, 6)]
        am.reconcile_player_rosters_across_matches(events)
        for e in events:
            self.assertNotIn("player_team_corrected_by_cross_match_consistency", e)

    def test_mega_and_regional_variants_count_as_agreement(self):
        events = [
            self._tp(1, "Mawile, Staraptor"),
            self._tp(2, "Mawile (Mega), Staraptor"),
            self._tp(3, "Mawile, Staraptor"),
            self._tp(4, "XXX, YYY"),
        ]
        am.reconcile_player_rosters_across_matches(events)
        self.assertEqual(events[3]["player_team"], "Mawile, Staraptor")

    def test_non_team_preview_events_are_ignored(self):
        real_team = "A, B, C, D, E, F"
        events = [
            {"event": "move_used", "match": 1, "pokemon": "A"},
            self._tp(1, real_team), self._tp(2, real_team), self._tp(3, real_team),
            self._tp(4, "totally different"),
        ]
        am.reconcile_player_rosters_across_matches(events)
        self.assertEqual(events[-1]["player_team"], real_team)


if __name__ == "__main__":
    unittest.main()
