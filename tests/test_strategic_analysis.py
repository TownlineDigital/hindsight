"""
Tests for strategic_analysis.py - the heuristic advantage-score/momentum-
timeline/resource-summary/mistake-candidate layer built on top of
decision_windows.py. See that module's own docstring for the (deliberately
repeated, load-bearing) caveat: nothing in here is a calibrated model, only
a bounded, monotonic heuristic - these tests check the ARITHMETIC and
WIRING are correct, not that any score is "the right" number (there is no
such thing for a heuristic by design).

Uses the same small synthetic-event-builder style as tests/test_decision_windows.py
for unit coverage, plus one integration test against the same real, public
[Gen 9 Champions] VGC 2026 Reg M-A replay (Geordivgc vs. JarlomenVGC) used in
tests/test_showdown_import.py, to prove the whole pipeline (Showdown import ->
decision windows -> strategic analysis) works end-to-end on real data.

Run: py -m unittest tests.test_strategic_analysis -v   (from poc-starter/)
"""

import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import strategic_analysis as sa  # noqa: E402


def _team_preview(match=1, ts=0.0, p_brought=None, o_brought=None):
    return {
        "event": "team_preview", "match": match, "timestamp": ts, "actor": "both",
        "player_brought": ", ".join(p_brought or []),
        "opponent_brought": ", ".join(o_brought or []),
    }


def _field_state(match, ts, turn, p_active, o_active, **extra):
    e = {
        "event": "field_state", "match": match, "timestamp": ts, "actor": "both",
        "turn": turn, "player_active": ", ".join(p_active), "opponent_active": ", ".join(o_active),
    }
    e.update(extra)
    return e


def _switch(match, ts, actor, pokemon):
    return {"event": "pokemon_sent_out", "match": match, "timestamp": ts, "actor": actor, "pokemon": pokemon}


def _faint(match, ts, actor, pokemon):
    return {"event": "pokemon_fainted", "match": match, "timestamp": ts, "actor": actor, "pokemon": pokemon}


def _move(match, ts, actor, pokemon):
    return {"event": "move_used", "match": match, "timestamp": ts, "actor": actor, "pokemon": pokemon, "move": "Tackle"}


def _stat_change(match, ts, actor, pokemon, detail):
    return {"event": "stat_change", "match": match, "timestamp": ts, "actor": actor, "pokemon": pokemon, "detail": detail}


def _battle_end(match, ts, winner):
    return {"event": "battle_end", "match": match, "timestamp": ts, "actor": winner, "winner": winner, "detail": "result"}


def _hp_change(match, ts, actor, pokemon, hp_percent):
    return {"event": "hp_change", "match": match, "timestamp": ts, "actor": actor,
            "pokemon": pokemon, "hp_percent": hp_percent, "detail": f"HP: {hp_percent}/100"}


class TestAdvantageScore(unittest.TestCase):
    def _window(self, player_alive, opponent_alive):
        return {
            "player": {"available_pokemon": ["mon"] * player_alive},
            "opponent": {"available_pokemon": ["mon"] * opponent_alive},
        }

    def test_even_numbers_score_zero(self):
        self.assertEqual(sa.compute_advantage_score(self._window(2, 2)), 0)

    def test_player_ahead_by_one(self):
        self.assertEqual(sa.compute_advantage_score(self._window(2, 1)), sa.ALIVE_WEIGHT)

    def test_player_behind_by_two(self):
        self.assertEqual(sa.compute_advantage_score(self._window(1, 3)), -2 * sa.ALIVE_WEIGHT)

    def test_score_clamped_to_range(self):
        score = sa.compute_advantage_score(self._window(6, 0))
        self.assertEqual(score, sa.SCORE_CLAMP)

    def test_tailwind_for_player_adds_bonus(self):
        even = sa.compute_advantage_score(self._window(2, 2))
        with_tw = sa.compute_advantage_score(self._window(2, 2), {"tailwind": "player"})
        self.assertEqual(with_tw - even, sa.TAILWIND_WEIGHT)

    def test_tailwind_for_opponent_subtracts(self):
        even = sa.compute_advantage_score(self._window(2, 2))
        with_tw = sa.compute_advantage_score(self._window(2, 2), {"tailwind": "opponent"})
        self.assertEqual(with_tw - even, -sa.TAILWIND_WEIGHT)

    def test_tailwind_both_or_none_or_missing_has_no_effect(self):
        even = sa.compute_advantage_score(self._window(2, 2))
        self.assertEqual(sa.compute_advantage_score(self._window(2, 2), {"tailwind": "both"}), even)
        self.assertEqual(sa.compute_advantage_score(self._window(2, 2), {"tailwind": "none"}), even)
        self.assertEqual(sa.compute_advantage_score(self._window(2, 2), None), even)


def _named_window(player_names, opponent_names):
    return {
        "player": {"available_pokemon": player_names},
        "opponent": {"available_pokemon": opponent_names},
    }


class TestAdvantageScoreHp(unittest.TestCase):
    """HP-percent-based scoring (task #129, added 2026-07-05) - see module
    docstring for the full honest-scope caveat. These tests check the
    ARITHMETIC and the "skip, don't guess" gating, same spirit as
    TestAdvantageScore's tailwind tests above."""

    def test_hp_diff_favors_the_healthier_side(self):
        window = _named_window(["Mon"], ["Mon"])
        hp_snapshot = {"player": {"mon": 80.0}, "opponent": {"mon": 20.0}}
        score = sa.compute_advantage_score(window, None, hp_snapshot)
        self.assertEqual(score, round((80.0 - 20.0) * sa.HP_WEIGHT))

    def test_hp_diff_favors_opponent_when_opponent_is_healthier(self):
        window = _named_window(["Mon"], ["Mon"])
        hp_snapshot = {"player": {"mon": 20.0}, "opponent": {"mon": 80.0}}
        score = sa.compute_advantage_score(window, None, hp_snapshot)
        self.assertEqual(score, round((20.0 - 80.0) * sa.HP_WEIGHT))

    def test_no_adjustment_when_only_one_side_has_known_hp(self):
        """A one-sided HP read (only the player's damage has ever been
        reported, say) can't produce a meaningful differential - must be
        skipped entirely, never compared against an assumed 100% for the
        side with no data."""
        window = _named_window(["Mon"], ["Mon"])
        even = sa.compute_advantage_score(window)
        only_player_known = sa.compute_advantage_score(window, None, {"player": {"mon": 10.0}, "opponent": {}})
        only_opponent_known = sa.compute_advantage_score(window, None, {"player": {}, "opponent": {"mon": 10.0}})
        self.assertEqual(only_player_known, even)
        self.assertEqual(only_opponent_known, even)

    def test_no_adjustment_when_hp_snapshot_is_none_or_empty(self):
        window = _named_window(["Mon"], ["Mon"])
        even = sa.compute_advantage_score(window)
        self.assertEqual(sa.compute_advantage_score(window, None, None), even)
        self.assertEqual(sa.compute_advantage_score(window, None, {}), even)

    def test_averages_multiple_known_hp_values_per_side(self):
        window = _named_window(["A", "B"], ["X", "Y"])
        hp_snapshot = {"player": {"a": 100.0, "b": 0.0}, "opponent": {"x": 50.0, "y": 50.0}}
        # player avg = 50, opponent avg = 50 -> no differential at all
        score = sa.compute_advantage_score(window, None, hp_snapshot)
        self.assertEqual(score, 0)

    def test_unknown_species_within_a_side_are_simply_excluded_from_the_average(self):
        """Only species with an actual entry in hp_snapshot contribute to the
        average - an alive-but-never-hit Pokemon isn't assumed to be at 100%.
        Equal alive counts (2 vs. 2) so the alive-count term is 0, isolating
        the HP term: "B" and "Y" have no hp_change data and must be excluded
        from their side's average, not treated as 100%."""
        window = _named_window(["A", "B"], ["X", "Y"])
        hp_snapshot = {"player": {"a": 40.0}, "opponent": {"x": 40.0}}  # "B"/"Y" unknown, excluded
        score = sa.compute_advantage_score(window, None, hp_snapshot)
        self.assertEqual(score, 0)

    def test_hp_adjustment_is_bounded_by_hp_weight(self):
        """Max possible differential is 100 points (100% vs 0%) - the score
        contribution can never exceed HP_WEIGHT * 100."""
        window = _named_window(["Mon"], ["Mon"])
        hp_snapshot = {"player": {"mon": 100.0}, "opponent": {"mon": 0.0}}
        score = sa.compute_advantage_score(window, None, hp_snapshot)
        self.assertEqual(score, round(100 * sa.HP_WEIGHT))

    def test_mega_evolved_species_key_still_matches_base_roster_name(self):
        """A Mega-evolved Pokemon's hp_change events are keyed under its
        post-Mega name in _turn_hp_snapshot (see _species_key), but
        available_pokemon always uses the base roster name - this must still
        resolve, not silently drop the HP read the moment a Pokemon Mega
        Evolves."""
        window = _named_window(["Kangaskhan"], ["Mon"])
        hp_snapshot = {"player": {"kangaskhan": 6.0}, "opponent": {"mon": 100.0}}
        score = sa.compute_advantage_score(window, None, hp_snapshot)
        self.assertEqual(score, round((6.0 - 100.0) * sa.HP_WEIGHT))


class TestSpeciesKey(unittest.TestCase):
    """_species_key's normalization - a local copy of decision_windows.py's
    own helper, used so a Mega-evolved/regional-form species name still
    resolves against the base roster name for HP lookups (see its own
    docstring for the real bug this avoids)."""

    def test_mega_y_suffix_stripped(self):
        self.assertEqual(sa._species_key("Charizard-Mega-Y"), sa._species_key("Charizard"))

    def test_plain_mega_suffix_stripped(self):
        self.assertEqual(sa._species_key("Kangaskhan-Mega"), sa._species_key("Kangaskhan"))

    def test_mega_prefix_form_stripped(self):
        self.assertEqual(sa._species_key("Mega Mawile"), sa._species_key("Mawile"))

    def test_regional_form_suffix_stripped(self):
        self.assertEqual(sa._species_key("Ninetales-Alola"), sa._species_key("Ninetales"))

    def test_different_species_still_produce_different_keys(self):
        self.assertNotEqual(sa._species_key("Charizard"), sa._species_key("Venusaur"))

    def test_case_and_punctuation_insensitive(self):
        self.assertEqual(sa._species_key("rotom-mow"), sa._species_key("Rotom-Mow"))


class TestTurnHpSnapshot(unittest.TestCase):
    def test_empty_dict_with_no_field_state_events(self):
        events = [_team_preview(p_brought=["A"], o_brought=["X"])]
        self.assertEqual(sa._turn_hp_snapshot(events), {})

    def test_untouched_pokemon_has_no_entry(self):
        """"Skip, don't guess" - a Pokemon with no hp_change event yet simply
        isn't in the snapshot, never defaulted to 100."""
        events = [
            _team_preview(p_brought=["A"], o_brought=["X"]),
            _field_state(1, 10, 1, ["A"], ["X"]),
        ]
        snap = sa._turn_hp_snapshot(events)
        self.assertEqual(snap[1], {"player": {}, "opponent": {}})

    def test_hp_change_this_turn_does_not_apply_to_this_turns_own_snapshot(self):
        """Same "snapshot reflects the START of the turn" ordering as
        decision_windows.py - an hp_change bucketed under turn 1 (i.e.
        occurring after turn 1's field_state) must not show up in turn 1's
        OWN snapshot, only turn 2's."""
        events = [
            _team_preview(p_brought=["A"], o_brought=["X"]),
            _field_state(1, 10, 1, ["A"], ["X"]),
            _hp_change(1, 15, "player", "A", 50.0),
            _field_state(1, 40, 2, ["A"], ["X"]),
        ]
        snap = sa._turn_hp_snapshot(events)
        self.assertEqual(snap[1]["player"], {})
        self.assertEqual(snap[2]["player"], {"a": 50.0})

    def test_later_hp_change_overwrites_earlier_value_for_the_same_species(self):
        events = [
            _team_preview(p_brought=["A"], o_brought=["X"]),
            _field_state(1, 10, 1, ["A"], ["X"]),
            _hp_change(1, 15, "player", "A", 80.0),
            _field_state(1, 40, 2, ["A"], ["X"]),
            _hp_change(1, 45, "player", "A", 30.0),
            _field_state(1, 70, 3, ["A"], ["X"]),
        ]
        snap = sa._turn_hp_snapshot(events)
        self.assertEqual(snap[3]["player"]["a"], 30.0)

    def test_mega_evolved_hp_change_merges_into_the_base_species_key(self):
        """A Pokemon's hp_change events reported under its post-Mega name
        still update the SAME tracked entry as its pre-Mega name, keyed by
        _species_key - a Mega-evolved Pokemon's HP history isn't split into
        two separate, half-known entries."""
        events = [
            _team_preview(p_brought=["Kangaskhan"], o_brought=["X"]),
            _field_state(1, 10, 1, ["Kangaskhan"], ["X"]),
            _hp_change(1, 15, "player", "Kangaskhan", 80.0),
            _field_state(1, 40, 2, ["Kangaskhan-Mega"], ["X"]),
            _hp_change(1, 45, "player", "Kangaskhan-Mega", 30.0),
            _field_state(1, 70, 3, ["Kangaskhan-Mega"], ["X"]),
        ]
        snap = sa._turn_hp_snapshot(events)
        self.assertEqual(snap[2]["player"], {"kangaskhan": 80.0})
        self.assertEqual(snap[3]["player"], {"kangaskhan": 30.0})

    def test_hp_change_missing_hp_percent_is_skipped(self):
        events = [
            _team_preview(p_brought=["A"], o_brought=["X"]),
            _field_state(1, 10, 1, ["A"], ["X"]),
            {"event": "hp_change", "match": 1, "timestamp": 15, "actor": "player", "pokemon": "A", "hp_percent": None},
            _field_state(1, 40, 2, ["A"], ["X"]),
        ]
        snap = sa._turn_hp_snapshot(events)
        self.assertEqual(snap[2]["player"], {})


class TestWinProbability(unittest.TestCase):
    def test_zero_score_is_fifty_percent(self):
        self.assertEqual(sa.estimate_win_probability(0), 50.0)

    def test_positive_score_favors_player(self):
        self.assertGreater(sa.estimate_win_probability(25), 50.0)

    def test_negative_score_favors_opponent(self):
        self.assertLess(sa.estimate_win_probability(-25), 50.0)

    def test_monotonic_in_score(self):
        low = sa.estimate_win_probability(10)
        mid = sa.estimate_win_probability(50)
        high = sa.estimate_win_probability(100)
        self.assertLess(low, mid)
        self.assertLess(mid, high)

    def test_never_claims_total_certainty_even_at_max_clamp(self):
        """A heuristic like this should never assert 0% or 100% - see module
        docstring's central caveat."""
        self.assertLess(sa.estimate_win_probability(sa.SCORE_CLAMP), 100.0)
        self.assertGreater(sa.estimate_win_probability(-sa.SCORE_CLAMP), 0.0)


class TestMomentumTimeline(unittest.TestCase):
    def test_empty_with_no_field_state_events(self):
        """Matches decision_windows.py's own behavior - nothing to key turns
        off, so this must not fabricate a fake turn 1."""
        events = [_team_preview(p_brought=["Sylveon"], o_brought=["Metagross"])]
        self.assertEqual(sa.build_momentum_timeline(events, 1), [])

    def test_one_entry_per_turn_first_delta_is_zero(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Incineroar"], o_brought=["Metagross", "Whimsicott"]),
            _field_state(1, 10, 1, ["Sylveon", "Incineroar"], ["Metagross", "Whimsicott"]),
            _field_state(1, 40, 2, ["Sylveon", "Incineroar"], ["Metagross", "Whimsicott"]),
        ]
        timeline = sa.build_momentum_timeline(events, 1)
        self.assertEqual([t["turn"] for t in timeline], [1, 2])
        self.assertEqual(timeline[0]["delta"], 0)

    def test_score_drops_after_a_faint_reduces_alive_count(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Incineroar"], o_brought=["Metagross", "Whimsicott"]),
            _field_state(1, 10, 1, ["Sylveon", "Incineroar"], ["Metagross", "Whimsicott"]),
            _faint(1, 20, "player", "Incineroar"),
            _field_state(1, 40, 2, ["Sylveon"], ["Metagross", "Whimsicott"]),
        ]
        timeline = sa.build_momentum_timeline(events, 1)
        turn1, turn2 = timeline
        self.assertEqual(turn1["score"], 0)
        self.assertLess(turn2["score"], turn1["score"])
        self.assertEqual(turn2["delta"], turn2["score"] - turn1["score"])

    def test_reasons_mention_the_fainted_pokemon(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Incineroar"], o_brought=["Metagross", "Whimsicott"]),
            _field_state(1, 10, 1, ["Sylveon", "Incineroar"], ["Metagross", "Whimsicott"]),
            _faint(1, 20, "player", "Incineroar"),
            _field_state(1, 40, 2, ["Sylveon"], ["Metagross", "Whimsicott"]),
        ]
        timeline = sa.build_momentum_timeline(events, 1)
        self.assertIn("Player lost Incineroar", timeline[1]["reasons"])

    def test_reasons_falls_back_to_no_notable_change(self):
        events = [
            _team_preview(p_brought=["Sylveon"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
            _field_state(1, 40, 2, ["Sylveon"], ["Metagross"]),
        ]
        timeline = sa.build_momentum_timeline(events, 1)
        self.assertEqual(timeline[1]["reasons"], ["No notable change this turn"])

    def test_new_tailwind_produces_a_reason_only_on_the_turn_it_starts(self):
        events = [
            _team_preview(p_brought=["Sylveon"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"], tailwind="none"),
            _field_state(1, 40, 2, ["Sylveon"], ["Metagross"], tailwind="player"),
            _field_state(1, 70, 3, ["Sylveon"], ["Metagross"], tailwind="player"),
        ]
        timeline = sa.build_momentum_timeline(events, 1)
        self.assertIn("Player gained Tailwind", timeline[1]["reasons"])
        self.assertNotIn("Player gained Tailwind", timeline[2]["reasons"])

    def test_alive_counts_reported_per_turn(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Incineroar"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon", "Incineroar"], ["Metagross"]),
        ]
        timeline = sa.build_momentum_timeline(events, 1)
        self.assertEqual(timeline[0]["player_alive"], 2)
        self.assertEqual(timeline[0]["opponent_alive"], 1)


class TestResourceSummary(unittest.TestCase):
    def test_none_for_empty_timeline(self):
        self.assertIsNone(sa.summarize_resources([]))

    def test_start_and_final_counts(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Incineroar"], o_brought=["Metagross", "Whimsicott"]),
            _field_state(1, 10, 1, ["Sylveon", "Incineroar"], ["Metagross", "Whimsicott"]),
            _faint(1, 20, "opponent", "Whimsicott"),
            _field_state(1, 40, 2, ["Sylveon", "Incineroar"], ["Metagross"]),
        ]
        timeline = sa.build_momentum_timeline(events, 1)
        summary = sa.summarize_resources(timeline)
        self.assertEqual(summary["turns_played"], 2)
        self.assertEqual(summary["player_alive_start"], 2)
        self.assertEqual(summary["opponent_alive_start"], 2)
        self.assertEqual(summary["opponent_alive_final"], 1)
        self.assertEqual(summary["final_win_probability"], timeline[-1]["win_probability"])


class TestMistakeCandidates(unittest.TestCase):
    def test_blind_switch_koed_flagged_when_switch_and_faint_share_a_turn(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Garchomp"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
            _switch(1, 15, "player", "Garchomp"),
            _faint(1, 16, "player", "Garchomp"),
            _field_state(1, 40, 2, ["Sylveon"], ["Metagross"]),
        ]
        flags = sa.flag_mistake_candidates(events, 1)
        blind = [f for f in flags if f["type"] == "blind_switch_koed"]
        self.assertEqual(len(blind), 1)
        self.assertEqual(blind[0]["side"], "player")
        self.assertEqual(blind[0]["turn"], 1)

    def test_not_flagged_when_switch_and_faint_are_different_turns(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Garchomp"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
            _switch(1, 15, "player", "Garchomp"),
            _field_state(1, 40, 2, ["Garchomp"], ["Metagross"]),
            _faint(1, 45, "player", "Garchomp"),
            _field_state(1, 70, 3, ["Sylveon"], ["Metagross"]),
        ]
        flags = sa.flag_mistake_candidates(events, 1)
        self.assertEqual([f for f in flags if f["type"] == "blind_switch_koed"], [])

    def test_big_momentum_swing_flagged_on_large_alive_count_change(self):
        events = [
            _team_preview(p_brought=["A", "B", "C"], o_brought=["X", "Y", "Z"]),
            _field_state(1, 10, 1, ["A", "B"], ["X", "Y"]),
            _faint(1, 15, "opponent", "X"),
            _faint(1, 16, "opponent", "Y"),
            _field_state(1, 40, 2, ["A", "B"], ["Z"]),
        ]
        flags = sa.flag_mistake_candidates(events, 1)
        swings = [f for f in flags if f["type"] == "big_momentum_swing"]
        self.assertEqual(len(swings), 1)
        self.assertEqual(swings[0]["turn"], 2)
        self.assertEqual(swings[0]["side"], "opponent")

    def test_no_swing_flag_for_a_small_change(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Incineroar"], o_brought=["Metagross", "Whimsicott"]),
            _field_state(1, 10, 1, ["Sylveon", "Incineroar"], ["Metagross", "Whimsicott"]),
            _field_state(1, 40, 2, ["Sylveon", "Incineroar"], ["Metagross", "Whimsicott"]),
        ]
        flags = sa.flag_mistake_candidates(events, 1)
        self.assertEqual(flags, [])

    def test_flags_sorted_by_turn(self):
        events = [
            _team_preview(p_brought=["A", "B", "C", "D"], o_brought=["X", "Y", "Z", "W"]),
            _field_state(1, 10, 1, ["A", "B"], ["X", "Y"]),
            _faint(1, 15, "opponent", "X"),
            _faint(1, 16, "opponent", "Y"),
            _field_state(1, 40, 2, ["A", "B"], ["Z", "W"]),
            _faint(1, 45, "player", "A"),
            _faint(1, 46, "player", "B"),
            _field_state(1, 70, 3, ["C", "D"], ["Z", "W"]),
        ]
        flags = sa.flag_mistake_candidates(events, 1)
        turns_seen = [f["turn"] for f in flags]
        self.assertEqual(turns_seen, sorted(turns_seen))


class TestParseStatChange(unittest.TestCase):
    def test_rose_is_positive_one(self):
        self.assertEqual(sa._parse_stat_change("Attack rose"), ("Attack", 1))

    def test_sharply_rose_is_still_just_positive_one(self):
        """Direction, not magnitude - this module only cares whether a stat
        went up or down, not how many stages, so "sharply rose" and "rose"
        both parse to +1."""
        self.assertEqual(sa._parse_stat_change("Speed sharply rose"), ("Speed", 1))

    def test_harshly_fell_is_negative_one(self):
        self.assertEqual(sa._parse_stat_change("Sp. Atk harshly fell"), ("Sp. Atk", -1))

    def test_capped_stat_is_not_a_real_change(self):
        self.assertIsNone(sa._parse_stat_change("Accuracy won't go any higher"))

    def test_unrecognized_text_returns_none(self):
        self.assertIsNone(sa._parse_stat_change("something unrelated"))

    def test_none_and_empty_are_handled(self):
        self.assertIsNone(sa._parse_stat_change(None))
        self.assertIsNone(sa._parse_stat_change(""))


class TestDesignatedSweeperCandidates(unittest.TestCase):
    def test_two_offensive_boosts_fire_a_candidate(self):
        events = [
            _team_preview(p_brought=["Gyarados", "Salazzle"], o_brought=["Charizard"]),
            _field_state(1, 10, 1, ["Gyarados", "Salazzle"], ["Charizard"]),
            _stat_change(1, 15, "player", "Gyarados", "Attack rose"),
            _field_state(1, 40, 2, ["Gyarados", "Salazzle"], ["Charizard"]),
            _stat_change(1, 45, "player", "Gyarados", "Speed rose"),
            _field_state(1, 70, 3, ["Gyarados", "Salazzle"], ["Charizard"]),
        ]
        candidates = sa.infer_win_condition_candidates(events, 1)
        sweepers = [c for c in candidates if c["type"] == "designated_sweeper"]
        self.assertEqual(len(sweepers), 1)
        self.assertEqual(sweepers[0]["pokemon"], "Gyarados")
        self.assertEqual(sweepers[0]["side"], "player")
        self.assertEqual(sweepers[0]["boost_count"], 2)
        self.assertEqual(sweepers[0]["turn_established"], 2)
        self.assertTrue(sweepers[0]["survived_to_last_turn_seen"])

    def test_one_boost_is_below_threshold_no_candidate(self):
        events = [
            _team_preview(p_brought=["Gyarados"], o_brought=["Charizard"]),
            _field_state(1, 10, 1, ["Gyarados"], ["Charizard"]),
            _stat_change(1, 15, "player", "Gyarados", "Attack rose"),
            _field_state(1, 40, 2, ["Gyarados"], ["Charizard"]),
        ]
        candidates = sa.infer_win_condition_candidates(events, 1)
        self.assertEqual([c for c in candidates if c["type"] == "designated_sweeper"], [])

    def test_survived_flag_is_false_when_the_sweeper_faints_later(self):
        events = [
            _team_preview(p_brought=["Gyarados", "Salazzle"], o_brought=["Charizard"]),
            _field_state(1, 10, 1, ["Gyarados", "Salazzle"], ["Charizard"]),
            _stat_change(1, 15, "player", "Gyarados", "Attack rose"),
            _stat_change(1, 16, "player", "Gyarados", "Speed rose"),
            _field_state(1, 40, 2, ["Gyarados", "Salazzle"], ["Charizard"]),
            _faint(1, 45, "player", "Gyarados"),
            _field_state(1, 70, 3, ["Salazzle"], ["Charizard"]),
        ]
        candidates = sa.infer_win_condition_candidates(events, 1)
        sweepers = [c for c in candidates if c["type"] == "designated_sweeper"]
        self.assertEqual(len(sweepers), 1)
        self.assertFalse(sweepers[0]["survived_to_last_turn_seen"])

    def test_unboost_does_not_count_toward_the_threshold(self):
        events = [
            _team_preview(p_brought=["Gyarados"], o_brought=["Charizard"]),
            _field_state(1, 10, 1, ["Gyarados"], ["Charizard"]),
            _stat_change(1, 15, "player", "Gyarados", "Attack rose"),
            _stat_change(1, 16, "player", "Gyarados", "Attack fell"),
            _field_state(1, 40, 2, ["Gyarados"], ["Charizard"]),
        ]
        candidates = sa.infer_win_condition_candidates(events, 1)
        self.assertEqual([c for c in candidates if c["type"] == "designated_sweeper"], [])

    def test_defensive_stat_boosts_do_not_count(self):
        """Defense/Sp. Def rising is a wall pattern, not a sweeper pattern -
        _OFFENSIVE_STATS deliberately excludes them."""
        events = [
            _team_preview(p_brought=["Clefable"], o_brought=["Charizard"]),
            _field_state(1, 10, 1, ["Clefable"], ["Charizard"]),
            _stat_change(1, 15, "player", "Clefable", "Defense rose"),
            _stat_change(1, 16, "player", "Clefable", "Sp. Def rose"),
            _field_state(1, 40, 2, ["Clefable"], ["Charizard"]),
        ]
        candidates = sa.infer_win_condition_candidates(events, 1)
        self.assertEqual([c for c in candidates if c["type"] == "designated_sweeper"], [])

    def test_no_actor_ocr_tier_event_is_skipped_not_guessed(self):
        """battle_text_parser.py's stat_change events never resolve `actor` -
        this must under-detect, never guess which side a boost belonged to."""
        events = [
            _team_preview(p_brought=["Gyarados"], o_brought=["Charizard"]),
            _field_state(1, 10, 1, ["Gyarados"], ["Charizard"]),
            _stat_change(1, 15, None, "Gyarados", "Attack rose"),
            _stat_change(1, 16, None, "Gyarados", "Speed rose"),
            _field_state(1, 40, 2, ["Gyarados"], ["Charizard"]),
        ]
        candidates = sa.infer_win_condition_candidates(events, 1)
        self.assertEqual([c for c in candidates if c["type"] == "designated_sweeper"], [])


class TestPrimaryCloserCandidates(unittest.TestCase):
    def test_pokemon_acting_on_two_ko_turns_is_flagged(self):
        events = [
            _team_preview(p_brought=["Garchomp", "Sylveon"], o_brought=["X", "Y", "Z"]),
            _field_state(1, 10, 1, ["Garchomp", "Sylveon"], ["X", "Y"]),
            _move(1, 15, "player", "Garchomp"),
            _faint(1, 16, "opponent", "X"),
            _field_state(1, 40, 2, ["Garchomp", "Sylveon"], ["Y"]),
            _move(1, 45, "player", "Garchomp"),
            _faint(1, 46, "opponent", "Y"),
            _field_state(1, 70, 3, ["Garchomp", "Sylveon"], ["Z"]),
        ]
        candidates = sa.infer_win_condition_candidates(events, 1)
        closers = [c for c in candidates if c["type"] == "primary_closer" and c["side"] == "player"]
        self.assertEqual(len(closers), 1)
        self.assertEqual(closers[0]["pokemon"], "Garchomp")
        self.assertEqual(closers[0]["count"], 2)

    def test_one_ko_adjacent_turn_is_below_threshold(self):
        events = [
            _team_preview(p_brought=["Garchomp"], o_brought=["X", "Y"]),
            _field_state(1, 10, 1, ["Garchomp"], ["X", "Y"]),
            _move(1, 15, "player", "Garchomp"),
            _faint(1, 16, "opponent", "X"),
            _field_state(1, 40, 2, ["Garchomp"], ["Y"]),
        ]
        candidates = sa.infer_win_condition_candidates(events, 1)
        self.assertEqual([c for c in candidates if c["type"] == "primary_closer"], [])

    def test_no_faints_at_all_produces_no_closer_candidates(self):
        events = [
            _team_preview(p_brought=["Garchomp"], o_brought=["X"]),
            _field_state(1, 10, 1, ["Garchomp"], ["X"]),
            _move(1, 15, "player", "Garchomp"),
            _field_state(1, 40, 2, ["Garchomp"], ["X"]),
        ]
        candidates = sa.infer_win_condition_candidates(events, 1)
        self.assertEqual([c for c in candidates if c["type"] == "primary_closer"], [])


class TestIdentifyThreats(unittest.TestCase):
    """Uses real species from backend/pokedex.SPECIES_TYPES so the type-chart
    math is checkable against real data, same spirit as
    backend/type_synergy.py's own tests."""

    def test_charizard_threatens_venusaur_but_not_sylveon(self):
        """Charizard (fire/flying): fire and flying are both super-effective
        against Venusaur (grass/poison, 2x from either type) but neutral
        against Sylveon (fairy, no listed fire/flying entry -> 1x)."""
        events = [
            _team_preview(p_brought=["Venusaur", "Sylveon"], o_brought=["Charizard"]),
            _field_state(1, 10, 1, ["Venusaur", "Sylveon"], ["Charizard"]),
        ]
        threats = sa.identify_threats(events, 1)
        self.assertEqual(len(threats), 1)
        self.assertEqual(threats[0]["pokemon"], "Charizard")
        self.assertEqual(threats[0]["side"], "opponent")
        self.assertEqual(threats[0]["threatens"], ["Venusaur"])
        self.assertEqual(threats[0]["threat_score"], 1.0)

    def test_quad_weakness_scores_higher(self):
        """Ninetales-Alola (ice/fairy): ice is 4x against Garchomp
        (dragon/ground) - a quad weakness should score above a plain single
        weakness (see test above, which scores 1.0 for one non-quad hit)."""
        events = [
            _team_preview(p_brought=["Garchomp"], o_brought=["Ninetales-Alola"]),
            _field_state(1, 10, 1, ["Garchomp"], ["Ninetales-Alola"]),
        ]
        threats = sa.identify_threats(events, 1)
        self.assertEqual(len(threats), 1)
        self.assertEqual(threats[0]["pokemon"], "Ninetales-Alola")
        self.assertEqual(threats[0]["threatens"], ["Garchomp"])
        self.assertEqual(threats[0]["threat_score"], 1.5)

    def test_unresolved_species_are_skipped_not_guessed(self):
        """A species not in pokedex.SPECIES_TYPES contributes nothing - no
        fabricated type guess for either side."""
        events = [
            _team_preview(p_brought=["TotallyMadeUpMon"], o_brought=["Charizard"]),
            _field_state(1, 10, 1, ["TotallyMadeUpMon"], ["Charizard"]),
        ]
        self.assertEqual(sa.identify_threats(events, 1), [])

    def test_no_threat_when_nothing_is_super_effective(self):
        events = [
            _team_preview(p_brought=["Sylveon"], o_brought=["Charizard"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Charizard"]),
        ]
        self.assertEqual(sa.identify_threats(events, 1), [])

    def test_empty_with_no_field_state_events(self):
        events = [_team_preview(p_brought=["Venusaur"], o_brought=["Charizard"])]
        self.assertEqual(sa.identify_threats(events, 1), [])

    def test_known_moves_seen_is_attached_but_not_scored(self):
        """A revealed move doesn't change the threat_score at all - it's
        purely reference context (see module docstring)."""
        events = [
            _team_preview(p_brought=["Venusaur"], o_brought=["Charizard"]),
            _field_state(1, 10, 1, ["Venusaur"], ["Charizard"]),
            _move(1, 15, "opponent", "Charizard"),
            _field_state(1, 40, 2, ["Venusaur"], ["Charizard"]),
        ]
        threats = sa.identify_threats(events, 1)
        self.assertEqual(len(threats), 1)
        self.assertEqual(threats[0]["known_moves_seen"], ["Tackle"])
        self.assertEqual(threats[0]["threat_score"], 1.0)

    def test_sorted_most_threatening_first(self):
        events = [
            _team_preview(p_brought=["Venusaur", "Garchomp"], o_brought=["Charizard", "Ninetales-Alola"]),
            _field_state(1, 10, 1, ["Venusaur", "Garchomp"], ["Charizard", "Ninetales-Alola"]),
        ]
        threats = sa.identify_threats(events, 1)
        self.assertEqual([t["pokemon"] for t in threats], ["Ninetales-Alola", "Charizard"])


class TestTraceLossToTurn(unittest.TestCase):
    def test_none_without_a_battle_end_event(self):
        events = [
            _team_preview(p_brought=["A"], o_brought=["X"]),
            _field_state(1, 10, 1, ["A"], ["X"]),
        ]
        self.assertIsNone(sa.trace_loss_to_turn(events, 1))

    def test_none_when_winner_is_unknown(self):
        events = [
            _team_preview(p_brought=["A"], o_brought=["X"]),
            _field_state(1, 10, 1, ["A"], ["X"]),
            _battle_end(1, 20, "unknown"),
        ]
        self.assertIsNone(sa.trace_loss_to_turn(events, 1))

    def test_none_with_no_field_state_events(self):
        events = [
            _team_preview(p_brought=["A"], o_brought=["X"]),
            _battle_end(1, 20, "player"),
        ]
        self.assertIsNone(sa.trace_loss_to_turn(events, 1))

    def test_clean_decisive_turn_never_recovered(self):
        """Opponent (winner) pulls ahead on turn 3 and the player (loser)
        never claws back to parity - turn 2 is the last turn the player was
        still even, so that's the decisive turn."""
        events = [
            _team_preview(p_brought=["A", "B"], o_brought=["X", "Y"]),
            _field_state(1, 10, 1, ["A", "B"], ["X", "Y"]),
            _field_state(1, 40, 2, ["A", "B"], ["X", "Y"]),
            _faint(1, 45, "player", "A"),
            _field_state(1, 70, 3, ["B"], ["X", "Y"]),
            _field_state(1, 100, 4, ["B"], ["X", "Y"]),
            _battle_end(1, 110, "opponent"),
        ]
        result = sa.trace_loss_to_turn(events, 1)
        self.assertEqual(result["loser"], "player")
        self.assertEqual(result["winner"], "opponent")
        self.assertEqual(result["decisive_turn"], 2)
        # A's faint happens after turn 2's field_state but before turn 3's -
        # same forward-assignment convention as _turn_faints elsewhere in
        # this module, so it's bucketed under turn 2, not turn 3.
        self.assertEqual(result["final_blow"], {"turn": 2, "pokemon": ["A"]})

    def test_already_behind_from_the_first_turn_gives_no_decisive_turn(self):
        events = [
            _team_preview(p_brought=["A"], o_brought=["X", "Y"]),
            _field_state(1, 10, 1, ["A"], ["X", "Y"]),
            _battle_end(1, 20, "opponent"),
        ]
        result = sa.trace_loss_to_turn(events, 1)
        self.assertEqual(result["loser"], "player")
        self.assertIsNone(result["decisive_turn"])

    def test_tied_through_the_last_turn_gives_no_decisive_turn(self):
        """A loser that was tied the whole time recorded (loses off-camera,
        after the last field_state) has no clean turn to point to."""
        events = [
            _team_preview(p_brought=["A"], o_brought=["X"]),
            _field_state(1, 10, 1, ["A"], ["X"]),
            _battle_end(1, 20, "opponent"),
        ]
        result = sa.trace_loss_to_turn(events, 1)
        self.assertIsNone(result["decisive_turn"])

    def test_last_tied_turn_counts_even_after_an_earlier_dip(self):
        """Player falls behind on turn 2, claws back to parity on turn 3,
        then falls behind for good on turn 4 - turn 3 is still a valid
        decisive turn: by definition nothing tied-or-ahead follows it, so
        the earlier dip on turn 2 doesn't disqualify it. The algorithm's
        "never recovered after this point" guarantee is about what comes
        AFTER the reported turn, not about a clean run-up to it."""
        events = [
            _team_preview(p_brought=["A", "B"], o_brought=["X", "Y"]),
            _field_state(1, 10, 1, ["A", "B"], ["X", "Y"]),
            _faint(1, 15, "player", "A"),
            _field_state(1, 40, 2, ["B"], ["X", "Y"]),
            _faint(1, 45, "opponent", "X"),
            _field_state(1, 70, 3, ["B"], ["Y"]),
            _faint(1, 75, "player", "B"),
            _field_state(1, 100, 4, [], ["Y"]),
            _battle_end(1, 110, "opponent"),
        ]
        result = sa.trace_loss_to_turn(events, 1)
        self.assertEqual(result["decisive_turn"], 3)

    def test_final_blow_is_none_when_loser_never_lost_a_pokemon_on_record(self):
        events = [
            _team_preview(p_brought=["A"], o_brought=["X"]),
            _field_state(1, 10, 1, ["A"], ["X"]),
            _battle_end(1, 20, "opponent"),
        ]
        result = sa.trace_loss_to_turn(events, 1)
        self.assertIsNone(result["final_blow"])


class TestAnalyzeMatchAndJob(unittest.TestCase):
    def test_analyze_match_bundles_everything(self):
        events = [
            _team_preview(p_brought=["Sylveon"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
        ]
        result = sa.analyze_match(events, 1)
        self.assertEqual(result["match"], 1)
        self.assertEqual(len(result["momentum_timeline"]), 1)
        self.assertIsNotNone(result["resource_summary"])
        self.assertEqual(result["mistake_candidates"], [])
        self.assertEqual(result["win_condition_candidates"], [])
        self.assertIsInstance(result["threats"], list)
        self.assertIsNone(result["loss_analysis"])  # no battle_end event in this fixture

    def test_analyze_job_separates_by_match(self):
        events = [
            _team_preview(match=1, p_brought=["Sylveon"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
            _team_preview(match=2, ts=300, p_brought=["Garchomp"], o_brought=["Whimsicott"]),
            _field_state(2, 310, 1, ["Garchomp"], ["Whimsicott"]),
        ]
        results = sa.analyze_job(events)
        self.assertEqual([r["match"] for r in results], [1, 2])

    def test_analyze_job_empty_events_returns_empty_list(self):
        self.assertEqual(sa.analyze_job([]), [])

    def test_analyze_job_does_not_let_one_bad_match_take_down_the_others(self):
        """Real regression (2026-07-09, job 303d13ba0940): one match's own
        messy raw data used to raise inside analyze_match, and analyze_job
        had no try/except - the exception propagated and NONE of the other
        29, perfectly fine matches in the job got analyzed either. Simulate
        that shape here without depending on real job data: monkeypatch
        analyze_match to raise only for match 2, and confirm match 1 and 3
        still come back with real results while match 2 gets a placeholder
        error entry instead of taking the whole call down."""
        events = [
            _team_preview(match=1, p_brought=["Sylveon"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
            _team_preview(match=2, ts=100, p_brought=["Garchomp"], o_brought=["Whimsicott"]),
            _field_state(2, 110, 1, ["Garchomp"], ["Whimsicott"]),
            _team_preview(match=3, ts=200, p_brought=["Corviknight"], o_brought=["Ninetales"]),
            _field_state(3, 210, 1, ["Corviknight"], ["Ninetales"]),
        ]
        real_analyze_match = sa.analyze_match

        def _flaky_analyze_match(match_events, match_number):
            if match_number == 2:
                raise TypeError("simulated: unsupported operand type(s) for +: 'float' and 'str'")
            return real_analyze_match(match_events, match_number)

        original = sa.analyze_match
        sa.analyze_match = _flaky_analyze_match
        try:
            results = sa.analyze_job(events)
        finally:
            sa.analyze_match = original

        self.assertEqual([r["match"] for r in results], [1, 2, 3])
        self.assertNotIn("error", results[0])
        self.assertIn("error", results[1])
        self.assertIn("TypeError", results[1]["error"])
        # The placeholder still has every key a real result has, so callers
        # (e.g. the frontend's turnReports lookup) never crash on a missing
        # field just because this one match failed.
        self.assertEqual(results[1]["momentum_timeline"], [])
        self.assertIsNone(results[1]["resource_summary"])
        self.assertIsNone(results[1]["loss_analysis"])
        self.assertNotIn("error", results[2])
        self.assertGreater(len(results[2]["momentum_timeline"]), 0)


class TestComputeJobBattleProfile(unittest.TestCase):
    """compute_job_battle_profile() (added 2026-07-09, tasks #234-237) -
    aggregates analyze_job()'s per-turn six-report data into a job-wide
    profile. These tests check the ARITHMETIC and WIRING (percentages,
    counts, which side/type things get bucketed under), same spirit as
    every other class in this file - not that any one profile number is
    "the right" skill assessment."""

    def test_none_for_empty_job_results(self):
        self.assertIsNone(sa.compute_job_battle_profile([]))

    def test_none_when_no_valid_match_has_any_turns(self):
        job_results = [
            {"match": 1, "error": "TypeError: boom", "momentum_timeline": [], "resource_summary": None,
             "mistake_candidates": [], "win_condition_candidates": [], "threats": [], "loss_analysis": None},
        ]
        self.assertIsNone(sa.compute_job_battle_profile(job_results))

    def test_matches_analyzed_and_errored_counted_separately(self):
        events = [
            _team_preview(match=1, p_brought=["Sylveon"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
        ]
        job_results = sa.analyze_job(events)
        job_results.append({
            "match": 2, "error": "TypeError: boom", "momentum_timeline": [], "resource_summary": None,
            "mistake_candidates": [], "win_condition_candidates": [], "threats": [], "loss_analysis": None,
        })
        profile = sa.compute_job_battle_profile(job_results)
        self.assertEqual(profile["matches_analyzed"], 1)
        self.assertEqual(profile["matches_errored"], 1)
        self.assertEqual(profile["turns_analyzed"], 1)

    def test_position_score_band_distribution_and_averages(self):
        events = [
            _team_preview(p_brought=["A", "B"], o_brought=["X"]),
            _field_state(1, 10, 1, ["A", "B"], ["X"]),
        ]
        job_results = sa.analyze_job(events)
        profile = sa.compute_job_battle_profile(job_results)
        self.assertEqual(profile["turns_analyzed"], 1)
        # player 2 alive vs opponent 1 alive -> score = ALIVE_WEIGHT -> "Slight Advantage"
        self.assertEqual(profile["position_score"]["band_distribution"]["Slight Advantage"], 100.0)
        self.assertEqual(profile["position_score"]["average"], sa.ALIVE_WEIGHT)
        self.assertEqual(profile["position_score"]["worst"], sa.ALIVE_WEIGHT)
        self.assertEqual(profile["position_score"]["best"], sa.ALIVE_WEIGHT)
        self.assertEqual(profile["position_score"]["final_turn_average"], sa.ALIVE_WEIGHT)

    def test_speed_control_side_distribution(self):
        events = [
            _team_preview(p_brought=["Regieleki"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Regieleki"], ["Metagross"]),
            _item_or_ability(1, 15, "player", "Regieleki", "item: Choice Scarf"),
            _field_state(1, 40, 2, ["Regieleki"], ["Metagross"]),
        ]
        job_results = sa.analyze_job(events)
        profile = sa.compute_job_battle_profile(job_results)
        # turn 1: not yet revealed ("none"); turn 2: known ("player") - 1 of 2 turns each
        self.assertEqual(profile["turns_analyzed"], 2)
        self.assertEqual(profile["speed_control"]["player_favorable_pct"], 50.0)
        self.assertEqual(profile["speed_control"]["none_pct"], 50.0)
        self.assertEqual(profile["speed_control"]["opponent_favorable_pct"], 0.0)
        self.assertEqual(profile["speed_control"]["contested_pct"], 0.0)

    def test_threat_pressure_tool_counts(self):
        events = [
            _team_preview(p_brought=["Incineroar"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Incineroar"], ["Metagross"]),
            _move_named(1, 15, "player", "Incineroar", "Fake Out"),
            _field_state(1, 40, 2, ["Incineroar"], ["Metagross"]),
        ]
        job_results = sa.analyze_job(events)
        profile = sa.compute_job_battle_profile(job_results)
        self.assertEqual(profile["threat_pressure"]["player_tool_counts"].get("fake_out"), 1)

    def test_resource_advantage_screen_uptime(self):
        events = [
            _team_preview(p_brought=["Sylveon"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"], screens="player Reflect"),
        ]
        job_results = sa.analyze_job(events)
        profile = sa.compute_job_battle_profile(job_results)
        self.assertEqual(profile["resource_advantage"]["player_screen_uptime_pct"], 100.0)
        self.assertEqual(profile["resource_advantage"]["opponent_screen_uptime_pct"], 0.0)

    def test_momentum_event_counts_and_direction_distribution(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Incineroar"], o_brought=["Metagross", "Whimsicott"]),
            _field_state(1, 10, 1, ["Sylveon", "Incineroar"], ["Metagross", "Whimsicott"]),
            _faint(1, 20, "player", "Incineroar"),
            _field_state(1, 40, 2, ["Sylveon"], ["Metagross", "Whimsicott"]),
        ]
        job_results = sa.analyze_job(events)
        profile = sa.compute_job_battle_profile(job_results)
        self.assertEqual(profile["momentum"]["event_counts"].get("own_pokemon_fainted"), 1)
        self.assertEqual(profile["momentum"]["event_counts"].get("opponent_pokemon_fainted"), 1)

    def test_risk_management_includes_every_posture_key_even_at_zero(self):
        events = [
            _team_preview(p_brought=["Sylveon"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
        ]
        job_results = sa.analyze_job(events)
        profile = sa.compute_job_battle_profile(job_results)
        self.assertEqual(
            set(profile["risk_management"].keys()),
            {"safe", "cautiously_safe", "balanced", "cautiously_aggressive", "aggressive"},
        )

    def test_mistake_patterns_counts_blind_switch_koed(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Garchomp"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
            _switch(1, 15, "player", "Garchomp"),
            _faint(1, 16, "player", "Garchomp"),
            _field_state(1, 40, 2, ["Sylveon"], ["Metagross"]),
        ]
        job_results = sa.analyze_job(events)
        profile = sa.compute_job_battle_profile(job_results)
        self.assertEqual(profile["mistake_patterns"]["counts_by_type"].get("blind_switch_koed"), 1)
        self.assertEqual(profile["mistake_patterns"]["matches_with_any_mistake"], 1)

    def test_win_condition_patterns_top_designated_sweeper(self):
        events = [
            _team_preview(p_brought=["Gyarados", "Salazzle"], o_brought=["Charizard"]),
            _field_state(1, 10, 1, ["Gyarados", "Salazzle"], ["Charizard"]),
            _stat_change(1, 15, "player", "Gyarados", "Attack rose"),
            _field_state(1, 40, 2, ["Gyarados", "Salazzle"], ["Charizard"]),
            _stat_change(1, 45, "player", "Gyarados", "Speed rose"),
            _field_state(1, 70, 3, ["Gyarados", "Salazzle"], ["Charizard"]),
        ]
        job_results = sa.analyze_job(events)
        profile = sa.compute_job_battle_profile(job_results)
        top = profile["win_condition_patterns"]["top_designated_sweepers"]
        self.assertEqual(top[0], {"pokemon": "Gyarados", "times_established": 1})
        self.assertEqual(profile["win_condition_patterns"]["top_primary_closers"], [])

    def test_loss_patterns_only_count_player_losses(self):
        events = [
            _team_preview(p_brought=["A", "B"], o_brought=["X", "Y"]),
            _field_state(1, 10, 1, ["A", "B"], ["X", "Y"]),
            _field_state(1, 40, 2, ["A", "B"], ["X", "Y"]),
            _faint(1, 45, "player", "A"),
            _field_state(1, 70, 3, ["B"], ["X", "Y"]),
            _field_state(1, 100, 4, ["B"], ["X", "Y"]),
            _battle_end(1, 110, "opponent"),
        ]
        job_results = sa.analyze_job(events)
        profile = sa.compute_job_battle_profile(job_results)
        self.assertEqual(profile["loss_patterns"]["losses_analyzed"], 1)
        self.assertEqual(profile["loss_patterns"]["average_decisive_turn"], 2.0)
        self.assertEqual(profile["loss_patterns"]["common_final_blow_pokemon"], [{"pokemon": "A", "count": 1}])

    def test_a_player_win_contributes_no_loss_pattern_data(self):
        events = [
            _team_preview(p_brought=["A", "B"], o_brought=["X"]),
            _field_state(1, 10, 1, ["A", "B"], ["X"]),
            _battle_end(1, 20, "player"),
        ]
        job_results = sa.analyze_job(events)
        profile = sa.compute_job_battle_profile(job_results)
        self.assertEqual(profile["loss_patterns"]["losses_analyzed"], 0)
        self.assertIsNone(profile["loss_patterns"]["average_decisive_turn"])
        self.assertEqual(profile["loss_patterns"]["common_final_blow_pokemon"], [])


class TestCoerceHpPercent(unittest.TestCase):
    """_coerce_hp_percent() (added 2026-07-09) - tolerant parsing for
    hp_percent values real video-sourced footage has actually produced that
    aren't a clean 0-100 number. Real regression: job 303d13ba0940's match 30
    had both "20%" and "1/164" hp_percent strings, which crashed
    compute_advantage_score's sum() with "unsupported operand type(s) for +:
    'float' and 'str'" before this existed."""

    def test_plain_int_passes_through_as_float(self):
        self.assertEqual(sa._coerce_hp_percent(82), 82.0)

    def test_plain_float_passes_through_unchanged(self):
        self.assertEqual(sa._coerce_hp_percent(82.5), 82.5)

    def test_percent_string_is_parsed(self):
        self.assertEqual(sa._coerce_hp_percent("20%"), 20.0)

    def test_plain_numeric_string_is_parsed(self):
        self.assertEqual(sa._coerce_hp_percent("55"), 55.0)

    def test_current_over_max_fraction_string_is_converted_to_a_percent(self):
        self.assertAlmostEqual(sa._coerce_hp_percent("1/164"), (1 / 164) * 100)

    def test_fraction_string_with_spaces_is_tolerated(self):
        self.assertAlmostEqual(sa._coerce_hp_percent("82 / 100"), 82.0)

    def test_none_is_treated_as_missing(self):
        self.assertIsNone(sa._coerce_hp_percent(None))

    def test_bool_is_not_mistaken_for_a_percent(self):
        self.assertIsNone(sa._coerce_hp_percent(True))

    def test_unparseable_string_is_treated_as_missing_not_a_crash(self):
        self.assertIsNone(sa._coerce_hp_percent("unknown"))

    def test_fraction_with_zero_max_is_treated_as_missing(self):
        self.assertIsNone(sa._coerce_hp_percent("0/0"))

    def test_turn_hp_snapshot_tolerates_a_mix_of_percent_and_fraction_strings(self):
        """The real end-to-end regression: _turn_hp_snapshot must not crash
        (and must produce a usable average) when different hp_change events
        in the SAME match report HP in different raw shapes."""
        events = [
            _team_preview(p_brought=["Sylveon"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
            _hp_change(1, 12, "player", "Sylveon", "20%"),
            _hp_change(1, 13, "opponent", "Metagross", "82/100"),
            _field_state(1, 20, 2, ["Sylveon"], ["Metagross"]),
        ]
        snap = sa._turn_hp_snapshot(events)
        self.assertEqual(snap[2]["player"]["sylveon"], 20.0)
        self.assertEqual(snap[2]["opponent"]["metagross"], 82.0)


# Verbatim from https://replay.pokemonshowdown.com/gen9championsvgc2026regma-2639736732.json
# (same real replay used in tests/test_showdown_import.py - Geordivgc beat
# JarlomenVGC in 12 turns).
REAL_REPLAY_JSON = r'''
{"id":"gen9championsvgc2026regma-2639736732","format":"[Gen 9 Champions] VGC 2026 Reg M-A","players":["Geordivgc","JarlomenVGC"],"log":"|j|☆Geordivgc\n|j|☆JarlomenVGC\n|t:|1782512570\n|gametype|doubles\n|player|p1|Geordivgc|worker|\n|player|p2|JarlomenVGC|hiker-gen4|\n|gen|9\n|tier|[Gen 9 Champions] VGC 2026 Reg M-A\n|rule|Species Clause: Limit one of each Pokémon\n|rule|Item Clause: Limit 1 of each item\n|clearpoke\n|poke|p1|Farigiraf, L50, M|\n|poke|p1|Rotom-Mow, L50|\n|poke|p1|Kangaskhan, L50, F|\n|poke|p1|Salazzle, L50, F|\n|poke|p1|Clefable, L50, M|\n|poke|p1|Gyarados, L50, M|\n|poke|p2|Charizard, L50, F|\n|poke|p2|Venusaur, L50, M|\n|poke|p2|Lucario, L50, F|\n|poke|p2|Rotom-Wash, L50|\n|poke|p2|Kangaskhan, L50, F|\n|poke|p2|Krookodile, L50, F|\n|teampreview|4\n|inactive|Battle timer is ON: inactive players will automatically lose when time's up. (requested by JarlomenVGC)\n|inactive|JarlomenVGC has 60 seconds left.\n|\n|t:|1782512616\n|teamsize|p1|4\n|teamsize|p2|4\n|start\n|switch|p1a: Salazzle|Salazzle, L50, F|100\/100\n|switch|p1b: Gyarados|Gyarados, L50, M|100\/100\n|switch|p2a: Charizard|Charizard, L50, F|100\/100\n|switch|p2b: Venusaur|Venusaur, L50, M|100\/100\n|-ability|p1b: Gyarados|Intimidate|boost\n|-unboost|p2a: Charizard|atk|1\n|-unboost|p2b: Venusaur|atk|1\n|turn|1\n|inactive|JarlomenVGC has 30 seconds left.\n|\n|t:|1782512659\n|switch|p2b: Krookodile|Krookodile, L50, F|100\/100\n|-ability|p2b: Krookodile|Intimidate|boost\n|detailschange|p2a: Charizard|Charizard-Mega-Y, L50, F\n|-mega|p2a: Charizard|Charizard|Charizardite Y\n|move|p1a: Salazzle|Fake Out|p2b: Krookodile\n|-damage|p2b: Krookodile|93\/100\n|move|p2a: Charizard|Solar Beam||[still]\n|move|p1b: Gyarados|Dragon Dance|p1b: Gyarados\n|-boost|p1b: Gyarados|atk|1\n|\n|upkeep\n|turn|2\n|\n|t:|1782512695\n|switch|p1a: Rotom|Rotom-Mow, L50|100\/100\n|move|p1b: Gyarados|Stone Edge|p2a: Charizard\n|-supereffective|p2a: Charizard|2\n|-damage|p2a: Charizard|0 fnt\n|faint|p2a: Charizard\n|move|p2b: Krookodile|Rock Slide|p1a: Rotom|[spread] p1a,p1b\n|-damage|p1a: Rotom|72\/100\n|-damage|p1b: Gyarados|23\/100\n|\n|upkeep\n|\n|t:|1782512709\n|switch|p2a: Kangaskhan|Kangaskhan, L50, F|100\/100\n|turn|3\n|\n|t:|1782512725\n|switch|p1a: Kangaskhan|Kangaskhan, L50, F|100\/100\n|move|p1b: Gyarados|Protect|p1b: Gyarados\n|move|p2a: Kangaskhan|Fake Out|p1a: Kangaskhan\n|-damage|p1a: Kangaskhan|77\/100\n|move|p2b: Krookodile|Crunch|p1a: Kangaskhan\n|-damage|p1a: Kangaskhan|22\/100\n|\n|upkeep\n|turn|4\n|\n|t:|1782512752\n|detailschange|p1a: Kangaskhan|Kangaskhan-Mega, L50, F\n|-mega|p1a: Kangaskhan|Kangaskhan|Kangaskhanite\n|move|p1a: Kangaskhan|Fake Out|p2a: Kangaskhan\n|-damage|p2a: Kangaskhan|76\/100\n|move|p1b: Gyarados|Waterfall|p2b: Krookodile\n|-damage|p2b: Krookodile|70\/100\n|move|p2b: Krookodile|Rock Slide|p1a: Kangaskhan|[spread] p1a,p1b\n|-damage|p1a: Kangaskhan|6\/100\n|-damage|p1b: Gyarados|0 fnt\n|faint|p1b: Gyarados\n|\n|upkeep\n|\n|t:|1782512772\n|switch|p1b: Rotom|Rotom-Mow, L50|72\/100\n|turn|5\n|\n|t:|1782512784\n|switch|p1a: Salazzle|Salazzle, L50, F|100\/100\n|move|p2b: Krookodile|Protect|p2b: Krookodile\n|move|p1b: Rotom|Leaf Storm|p2b: Krookodile\n|move|p2a: Kangaskhan|Last Resort|p1b: Rotom\n|-damage|p1b: Rotom|0 fnt\n|faint|p1b: Rotom\n|\n|upkeep\n|\n|t:|1782512794\n|switch|p1b: Kangaskhan|Kangaskhan-Mega, L50, F|6\/100\n|turn|6\n|\n|t:|1782512806\n|move|p1b: Kangaskhan|Fake Out|p2a: Kangaskhan\n|-damage|p2a: Kangaskhan|49\/100\n|move|p1a: Salazzle|Encore|p2b: Krookodile\n|move|p2b: Krookodile|Protect||[still]\n|\n|upkeep\n|turn|7\n|\n|t:|1782512843\n|move|p2b: Krookodile|Protect|p2b: Krookodile\n|move|p1a: Salazzle|Sludge Bomb|p2a: Kangaskhan\n|-damage|p2a: Kangaskhan|0 fnt\n|faint|p2a: Kangaskhan\n|move|p1b: Kangaskhan|Hammer Arm|p2b: Krookodile\n|\n|upkeep\n|\n|t:|1782512850\n|switch|p2a: Venusaur|Venusaur, L50, M|100\/100\n|turn|8\n|\n|t:|1782512870\n|move|p2b: Krookodile|Protect|p2b: Krookodile\n|move|p1b: Kangaskhan|Protect|p1b: Kangaskhan\n|move|p1a: Salazzle|Heat Wave|p2b: Krookodile|[spread] p2a\n|-damage|p2a: Venusaur|26\/100\n|move|p2a: Venusaur|Earth Power|p1a: Salazzle\n|-damage|p1a: Salazzle|1\/100\n|\n|upkeep\n|turn|9\n|\n|t:|1782512906\n|move|p2a: Venusaur|Protect|p2a: Venusaur\n|move|p1a: Salazzle|Encore|p2b: Krookodile\n|move|p1b: Kangaskhan|Hammer Arm|p2a: Venusaur\n|\n|upkeep\n|turn|10\n|\n|t:|1782512919\n|move|p2b: Krookodile|Protect|p2b: Krookodile\n|move|p1a: Salazzle|Encore|p2a: Venusaur\n|move|p1b: Kangaskhan|Hammer Arm|p2b: Krookodile\n|\n|upkeep\n|turn|11\n|\n|t:|1782512929\n|move|p2b: Krookodile|Protect||[still]\n|move|p2a: Venusaur|Protect|p2a: Venusaur\n|move|p1a: Salazzle|Heat Wave|p2a: Venusaur|[spread] p2b\n|-damage|p2b: Krookodile|21\/100\n|move|p1b: Kangaskhan|Hammer Arm|p2b: Krookodile\n|-damage|p2b: Krookodile|0 fnt\n|faint|p2b: Krookodile\n|\n|upkeep\n|turn|12\n|\n|t:|1782512941\n|move|p2a: Venusaur|Protect||[still]\n|move|p1a: Salazzle|Heat Wave|p2a: Venusaur\n|-damage|p2a: Venusaur|0 fnt\n|faint|p2a: Venusaur\n|\n|win|Geordivgc\n","uploadtime":1782512948,"views":33,"formatid":"gen9championsvgc2026regma","rating":null,"private":0,"password":null}
'''.strip()


class TestRealReplayIntegration(unittest.TestCase):
    """End-to-end: Showdown import -> decision windows -> strategic analysis,
    on the same real, public replay used elsewhere in this test suite. Proves
    the full chain works on real data, not just synthetic fixtures - the same
    standard tests/test_showdown_import.py already holds itself to."""

    def setUp(self):
        import showdown_import as si
        self.events = si.parse_replay(REAL_REPLAY_JSON, match_number=1, player_id="Geordivgc")
        self.result = sa.analyze_match(self.events, 1)

    def test_twelve_turn_timeline(self):
        self.assertEqual(len(self.result["momentum_timeline"]), 12)
        self.assertEqual([t["turn"] for t in self.result["momentum_timeline"]], list(range(1, 13)))

    def test_both_sides_start_at_four_alive_the_full_brought_squad(self):
        """player_alive/opponent_alive count ALIVE OUT OF THE BROUGHT-4
        ROSTER (decision_windows.py's `available_pokemon`), not how many are
        currently on the field (always 2 in doubles) - real "resource
        tracking" means the whole remaining squad, not just the active
        slots. Nothing has fainted yet at turn 1, so both sides show their
        full brought-4."""
        first = self.result["momentum_timeline"][0]
        self.assertEqual(first["player_alive"], 4)
        self.assertEqual(first["opponent_alive"], 4)

    def test_player_wins_so_final_win_probability_favors_player(self):
        """Geordivgc (the named --player) actually won this real match - the
        final turn's win_probability should end up on the player's side of
        50%, since the player is ahead in alive-Pokemon count (2 vs. 1)
        going into the match's last turn."""
        self.assertGreater(self.result["resource_summary"]["final_win_probability"], 50.0)

    def test_resource_summary_reflects_the_real_ko_count(self):
        """3 of the opponent's real brought Pokemon have already fainted
        BEFORE the match's final turn (turn 12) begins - Charizard (as
        Charizard-Mega-Y - see decision_windows.py's _species_key fix,
        2026-07-04, for why its post-Mega faint name still correctly counts
        against the base "Charizard" roster entry), Kangaskhan, and
        Krookodile - leaving Venusaur as the 1 still alive going INTO turn
        12 (it faints DURING that turn, ending the match - see
        summarize_resources' own docstring for why "alive going into the
        last turn," not "alive after it," is the correct, honest semantic
        here). Player side: 2 alive going into the last turn (Salazzle,
        Kangaskhan) - Gyarados and Rotom already fainted earlier."""
        summary = self.result["resource_summary"]
        self.assertEqual(summary["opponent_alive_final"], 1)
        self.assertEqual(summary["player_alive_final"], 2)

    def test_analyze_job_works_on_the_real_showdown_import_too(self):
        results = sa.analyze_job(self.events)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["match"], 1)

    def test_no_crash_computing_mistake_candidates_on_real_data(self):
        """Doesn't assert any specific flag fires (that would be over-fitting
        a heuristic to one match) - just that it runs cleanly end-to-end on
        real, messy data and returns a list."""
        self.assertIsInstance(self.result["mistake_candidates"], list)

    def test_loss_analysis_traces_the_opponents_loss_to_turn_11(self):
        """Manually traced against the real log: the opponent (loser) was
        tied 2-2 on alive count through turn 11, then fell to 2-1 on turn 12
        (Venusaur's faint, ending the match) and never recovered - turn 11
        is the clean decisive turn, and Venusaur's turn-12 faint is the
        final blow."""
        loss = self.result["loss_analysis"]
        self.assertIsNotNone(loss)
        self.assertEqual(loss["winner"], "player")
        self.assertEqual(loss["loser"], "opponent")
        self.assertEqual(loss["decisive_turn"], 11)
        self.assertEqual(loss["final_blow"], {"turn": 12, "pokemon": ["Venusaur"]})

    def test_no_threats_resolve_given_this_replays_limited_pokedex_coverage(self):
        """Confirmed by running identify_threats directly against this real
        replay: backend/pokedex.SPECIES_TYPES only covers a hand-picked
        subset of species, and this replay's actual brought rosters barely
        overlap with it (only Farigiraf and Kangaskhan resolve on the player
        side; Charizard, Venusaur, and Kangaskhan on the opponent side -
        Krookodile, Lucario, Rotom-Wash, Salazzle, Clefable, and Gyarados
        are all unresolved and correctly skipped). None of the resolved
        opponent species happen to be super-effective against either
        resolved player species under this project's type chart, so an
        empty list is the honest, correct result here - not a bug."""
        self.assertEqual(self.result["threats"], [])

    def test_no_designated_sweeper_since_gyarados_only_gets_one_boost(self):
        """The only |-boost| line in this whole replay is Gyarados' single
        Dragon Dance (turn 2) - one offensive boost, below
        SWEEPER_BOOST_THRESHOLD (2), so this pattern correctly finds nothing
        to flag. The two |-unboost| lines (Intimidate lowering Charizard's
        and Venusaur's Attack, turn 1) don't count either way - they're
        negative-direction and on the opponent's side."""
        candidates = self.result["win_condition_candidates"]
        self.assertEqual([c for c in candidates if c["type"] == "designated_sweeper"], [])

    def test_salazzle_is_the_players_primary_closer(self):
        """Manually traced against the real log: Salazzle has a move recorded
        on 3 of the turns the opponent lost a Pokemon - the clear standout on
        the player's side."""
        candidates = self.result["win_condition_candidates"]
        player_closers = [c for c in candidates if c["type"] == "primary_closer" and c["side"] == "player"]
        self.assertEqual(len(player_closers), 1)
        self.assertEqual(player_closers[0]["pokemon"], "Salazzle")
        self.assertEqual(player_closers[0]["count"], 3)

    def test_turn_6_score_reflects_known_hp_not_just_alive_count(self):
        """Manually traced + confirmed via direct computation against this
        real replay (2026-07-05): turn 6's alive-count-only score would be
        -33 (player 2 alive vs. opponent 3 alive, no Tailwind) - but by turn
        6 there's real, known HP on both sides (player: Rotom-Mow/Gyarados
        both fainted/0%, Kangaskhan-Mega at 6% (merged with its pre-Mega 22%
        history via _species_key - see TestTurnHpSnapshot); opponent:
        Krookodile 70%, Kangaskhan 76%, Charizard-Mega-Y 0%), so the score
        now also reflects the opponent's healthier known survivors, landing
        at -35 instead of the old HP-blind -33."""
        turn6 = next(t for t in self.result["momentum_timeline"] if t["turn"] == 6)
        self.assertEqual(turn6["score"], -35)

    def test_hp_snapshot_has_real_known_values_by_turn_6(self):
        match_events = [e for e in self.events if e.get("match") == 1]
        snap = sa._turn_hp_snapshot(match_events)
        turn6 = snap[6]
        self.assertEqual(turn6["player"]["kangaskhan"], 6.0)  # merged Mega history
        self.assertEqual(turn6["opponent"]["krookodile"], 70.0)
        self.assertEqual(turn6["opponent"]["kangaskhan"], 76.0)

    def test_opponent_has_a_primary_closer_tied_between_two_candidates(self):
        """Kangaskhan and Krookodile are genuinely tied at 2 KO-adjacent turns
        each on the opponent's side - Counter.most_common's tie-break isn't a
        meaningful signal, so this only asserts a candidate exists with a
        valid count and pokemon, not which of the two comes out on top."""
        candidates = self.result["win_condition_candidates"]
        opp_closers = [c for c in candidates if c["type"] == "primary_closer" and c["side"] == "opponent"]
        self.assertEqual(len(opp_closers), 1)
        self.assertGreaterEqual(opp_closers[0]["count"], 2)
        self.assertIn(opp_closers[0]["pokemon"], ("Kangaskhan", "Krookodile"))


def _move_named(match, ts, actor, pokemon, move):
    return {"event": "move_used", "match": match, "timestamp": ts, "actor": actor, "pokemon": pokemon, "move": move}


def _item_or_ability(match, ts, actor, pokemon, detail):
    return {"event": "item_or_ability_activated", "match": match, "timestamp": ts, "actor": actor,
            "pokemon": pokemon, "detail": detail}


class TestComputeSpeedControl(unittest.TestCase):
    """Report #1 (added 2026-07-09, VGC Battle Intelligence Manual). Tailwind
    and Trick Room are FACTORS ONLY here (see the function's own docstring
    for why re-scoring them would double-count `score`) - only revealed
    speed-control items/abilities move this report's own `score`."""

    def test_tailwind_is_a_factor_but_not_scored(self):
        result = sa.compute_speed_control({"tailwind": "player"}, None, set())
        self.assertEqual(result["score"], 0)
        self.assertTrue(any("Tailwind" in f for f in result["factors"]))
        self.assertEqual(result["side"], "none")

    def test_both_sides_tailwind_is_contested_even_at_zero_score(self):
        result = sa.compute_speed_control({"tailwind": "both"}, None, set())
        self.assertEqual(result["side"], "contested")

    def test_trick_room_setter_known_to_be_player(self):
        result = sa.compute_speed_control({"trick_room": True}, None, {"player"})
        self.assertTrue(any("Player set it up" in f for f in result["factors"]))
        self.assertEqual(result["score"], 0)  # trick room is never scored, see docstring

    def test_trick_room_setter_known_to_be_opponent(self):
        result = sa.compute_speed_control({"trick_room": True}, None, {"opponent"})
        self.assertTrue(any("Opponent set it up" in f for f in result["factors"]))

    def test_trick_room_setter_unknown(self):
        result = sa.compute_speed_control({"trick_room": True}, None, set())
        self.assertTrue(any("isn't determinable" in f for f in result["factors"]))

    def test_trick_room_active_with_no_tailwind_or_tools_is_contested(self):
        result = sa.compute_speed_control({"trick_room": True}, None, set())
        self.assertEqual(result["side"], "contested")

    def test_revealed_choice_scarf_scores_for_player(self):
        speed_tools = {"player": {("Regieleki", "Choice Scarf")}, "opponent": set()}
        result = sa.compute_speed_control(None, speed_tools, set())
        self.assertEqual(result["score"], sa.SPEED_TOOL_WEIGHT)
        self.assertEqual(result["side"], "player")
        self.assertTrue(any("Regieleki" in f and "Choice Scarf" in f for f in result["factors"]))

    def test_revealed_speed_ability_scores_negative_for_opponent(self):
        speed_tools = {"player": set(), "opponent": {("Barraskewda", "Swift Swim")}}
        result = sa.compute_speed_control(None, speed_tools, set())
        self.assertEqual(result["score"], -sa.SPEED_TOOL_WEIGHT)
        self.assertEqual(result["side"], "opponent")

    def test_score_is_clamped(self):
        many_tools = {(f"Mon{i}", "Choice Scarf") for i in range(20)}
        speed_tools = {"player": many_tools, "opponent": set()}
        result = sa.compute_speed_control(None, speed_tools, set())
        self.assertEqual(result["score"], sa.SPEED_SCORE_CLAMP)

    def test_no_factors_at_all_reports_none(self):
        result = sa.compute_speed_control(None, None, set())
        self.assertEqual(result["factors"], ["No speed-control factors detected this turn"])
        self.assertEqual(result["side"], "none")
        self.assertEqual(result["score"], 0)


class TestComputeThreatPressure(unittest.TestCase):
    """Report #2. KOs-this-turn are a FACTOR only (already reflected one
    turn later via `score`'s own alive-count term - see docstring); only
    revealed danger-move categories on the current board move this report's
    own `score`."""

    def _window(self, player_moves=None, opponent_moves=None):
        return {
            "player": {"known_moves": player_moves or {}},
            "opponent": {"known_moves": opponent_moves or {}},
        }

    def test_fake_out_on_player_board_scores_positive(self):
        window = self._window(player_moves={"Incineroar": ["Fake Out"]})
        result = sa.compute_threat_pressure(window, {})
        self.assertEqual(result["score"], sa.THREAT_TOOL_WEIGHT)
        self.assertEqual(result["side"], "player")
        self.assertEqual(result["player_tools"], ["fake_out"])

    def test_redirection_on_opponent_board_scores_negative(self):
        window = self._window(opponent_moves={"Indeedee": ["Follow Me"]})
        result = sa.compute_threat_pressure(window, {})
        self.assertEqual(result["score"], -sa.THREAT_TOOL_WEIGHT)
        self.assertEqual(result["side"], "opponent")
        self.assertEqual(result["opponent_tools"], ["redirection"])

    def test_spread_move_detected(self):
        window = self._window(player_moves={"Rillaboom": ["Rock Slide"]})
        result = sa.compute_threat_pressure(window, {})
        self.assertEqual(result["player_tools"], ["spread"])

    def test_kos_this_turn_are_a_factor_not_a_score(self):
        window = self._window()
        no_ko = sa.compute_threat_pressure(window, {})
        with_ko = sa.compute_threat_pressure(window, {"opponent": ["Charizard"]})
        self.assertEqual(no_ko["score"], with_ko["score"])
        self.assertTrue(any("scored 1 KO" in f for f in with_ko["factors"]))

    def test_no_factors_reports_even(self):
        result = sa.compute_threat_pressure(self._window(), {})
        self.assertEqual(result["factors"], ["No notable threat-pressure factors this turn"])
        self.assertEqual(result["side"], "even")


class TestComputeResourceAdvantage(unittest.TestCase):
    """Report #3. board_score mirrors compute_advantage_score's own alive/HP
    arithmetic (ALIVE_WEIGHT, HP_WEIGHT) - only `screen_score` is new,
    non-overlapping information (see docstring on why compute_position_score
    only ever folds in screen_score, never board_score)."""

    def _window(self, player_names, opponent_names):
        return {
            "player": {"available_pokemon": player_names},
            "opponent": {"available_pokemon": opponent_names},
        }

    def test_board_score_matches_alive_weight_arithmetic(self):
        result = sa.compute_resource_advantage(self._window(["A", "B"], ["X"]), None, None)
        self.assertEqual(result["board_score"], sa.ALIVE_WEIGHT)
        self.assertEqual(result["player_alive"], 2)
        self.assertEqual(result["opponent_alive"], 1)

    def test_hp_averages_reported(self):
        window = self._window(["Mon"], ["Mon"])
        hp_snapshot = {"player": {"mon": 80.0}, "opponent": {"mon": 20.0}}
        result = sa.compute_resource_advantage(window, None, hp_snapshot)
        self.assertEqual(result["player_avg_hp"], 80.0)
        self.assertEqual(result["opponent_avg_hp"], 20.0)

    def test_no_hp_known_reports_none(self):
        result = sa.compute_resource_advantage(self._window(["Mon"], ["Mon"]), None, None)
        self.assertIsNone(result["player_avg_hp"])
        self.assertIsNone(result["opponent_avg_hp"])

    def test_player_screen_scores_positive(self):
        window = self._window(["A"], ["X"])
        result = sa.compute_resource_advantage(window, {"screens": "player Reflect"}, None)
        self.assertEqual(result["screen_score"], sa.RESOURCE_SCREEN_WEIGHT)
        self.assertTrue(result["screens"]["player"])
        self.assertFalse(result["screens"]["opponent"])

    def test_opponent_screen_scores_negative(self):
        window = self._window(["A"], ["X"])
        result = sa.compute_resource_advantage(window, {"screens": "opponent Aurora Veil"}, None)
        self.assertEqual(result["screen_score"], -sa.RESOURCE_SCREEN_WEIGHT)

    def test_combined_score_is_board_plus_screen(self):
        window = self._window(["A", "B"], ["X"])
        result = sa.compute_resource_advantage(window, {"screens": "player Reflect"}, None)
        self.assertEqual(result["score"], result["board_score"] + result["screen_score"])

    def test_no_screens_reports_false_for_both_sides(self):
        result = sa.compute_resource_advantage(self._window(["A"], ["X"]), None, None)
        self.assertFalse(result["screens"]["player"])
        self.assertFalse(result["screens"]["opponent"])


class TestComputeMomentum(unittest.TestCase):
    """Report #4. `delta` is never re-derived here - Momentum only
    categorizes the SAME swing `score`'s own delta already represents onto
    the manual's explicit event list."""

    def test_own_faint_and_opponent_gain_are_both_emitted(self):
        result = sa.compute_momentum(-25, {"player": {"Incineroar"}, "opponent": set()}, None, None, None)
        negative = [e for e in result["events"] if e["category"] == "negative"]
        positive = [e for e in result["events"] if e["category"] == "positive"]
        self.assertTrue(any(e["type"] == "own_pokemon_fainted" and e["side"] == "player" for e in negative))
        self.assertTrue(any(e["type"] == "opponent_pokemon_fainted" and e["side"] == "opponent" for e in positive))

    def test_big_stat_boost_is_positive(self):
        stat_changes = {"player": [("Gyarados", "Attack", 1)]}
        result = sa.compute_momentum(5, {"player": set(), "opponent": set()}, stat_changes, None, None)
        boosts = [e for e in result["events"] if e["type"] == "big_stat_boost"]
        self.assertEqual(len(boosts), 1)
        self.assertEqual(boosts[0]["category"], "positive")
        self.assertEqual(boosts[0]["side"], "player")

    def test_defensive_stat_change_is_not_a_big_stat_boost(self):
        stat_changes = {"player": [("Clefable", "Defense", 1)]}
        result = sa.compute_momentum(0, {"player": set(), "opponent": set()}, stat_changes, None, None)
        self.assertEqual([e for e in result["events"] if e["type"] == "big_stat_boost"], [])

    def test_screen_established_is_positive(self):
        result = sa.compute_momentum(0, {"player": set(), "opponent": set()}, None,
                                      {"player": True, "opponent": False}, None)
        established = [e for e in result["events"] if e["type"] == "screen_established"]
        self.assertEqual(len(established), 1)
        self.assertEqual(established[0]["side"], "player")

    def test_failed_move_is_context_never_positive_or_negative(self):
        result = sa.compute_momentum(0, {"player": set(), "opponent": set()}, None, None,
                                      {"player": ["Incineroar"], "opponent": []})
        failed = [e for e in result["events"] if e["type"] == "move_failed_or_blocked"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["category"], "context")

    def test_direction_bands(self):
        empty = {"player": set(), "opponent": set()}
        self.assertEqual(sa.compute_momentum(sa.MOMENTUM_NEUTRAL_BAND + 1, empty, None, None, None)["direction"],
                         "gained")
        self.assertEqual(sa.compute_momentum(-(sa.MOMENTUM_NEUTRAL_BAND + 1), empty, None, None, None)["direction"],
                         "lost")
        self.assertEqual(sa.compute_momentum(sa.MOMENTUM_NEUTRAL_BAND, empty, None, None, None)["direction"],
                         "neutral")


class TestPositionScoreLabel(unittest.TestCase):
    """Verbatim VGC Battle Intelligence Manual bands."""

    def test_exact_band_boundaries(self):
        self.assertEqual(sa.position_score_label(100), "Dominating")
        self.assertEqual(sa.position_score_label(80), "Dominating")
        self.assertEqual(sa.position_score_label(79), "Strong Advantage")
        self.assertEqual(sa.position_score_label(50), "Strong Advantage")
        self.assertEqual(sa.position_score_label(49), "Slight Advantage")
        self.assertEqual(sa.position_score_label(20), "Slight Advantage")
        self.assertEqual(sa.position_score_label(19), "Even")
        self.assertEqual(sa.position_score_label(0), "Even")
        self.assertEqual(sa.position_score_label(-19), "Even")
        self.assertEqual(sa.position_score_label(-20), "Slight Disadvantage")
        self.assertEqual(sa.position_score_label(-49), "Slight Disadvantage")
        self.assertEqual(sa.position_score_label(-50), "Major Disadvantage")
        self.assertEqual(sa.position_score_label(-79), "Major Disadvantage")
        self.assertEqual(sa.position_score_label(-80), "Losing")
        self.assertEqual(sa.position_score_label(-100), "Losing")

    def test_out_of_range_scores_are_clamped_first(self):
        self.assertEqual(sa.position_score_label(500), "Dominating")
        self.assertEqual(sa.position_score_label(-500), "Losing")


class TestComputePositionScore(unittest.TestCase):
    """Report #5: composes `score` with each sub-report's own NEW,
    non-overlapping signal only (speed_control's tool score, threat_pressure's
    tool score, resource_advantage's screen_score) - never resource_advantage's
    board_score, which would double-count `score`'s own alive/HP terms."""

    def test_composes_only_the_new_signals(self):
        speed_control = {"score": 5}
        threat_pressure = {"score": -5}
        resource_advantage = {"score": 999, "board_score": 999, "screen_score": 8}
        result = sa.compute_position_score(20, speed_control, threat_pressure, resource_advantage)
        # 20 (base score) + 5 (speed) - 5 (threat) + 8 (screen_score only, NOT board_score's 999)
        self.assertEqual(result["value"], 28)

    def test_none_sub_reports_contribute_nothing(self):
        result = sa.compute_position_score(20, None, None, None)
        self.assertEqual(result["value"], 20)

    def test_label_matches_position_score_label(self):
        result = sa.compute_position_score(90, None, None, None)
        self.assertEqual(result["label"], "Dominating")

    def test_value_is_clamped_to_100(self):
        result = sa.compute_position_score(100, {"score": 30}, {"score": 30}, {"score": 0, "screen_score": 30})
        self.assertEqual(result["value"], 100)


class TestComputeRiskManagement(unittest.TestCase):
    """Report #6: posture is purely a function of Position Score's band."""

    def test_dominating_is_safe(self):
        self.assertEqual(sa.compute_risk_management("Dominating")["posture"], "safe")

    def test_losing_is_aggressive(self):
        self.assertEqual(sa.compute_risk_management("Losing")["posture"], "aggressive")

    def test_even_is_balanced(self):
        self.assertEqual(sa.compute_risk_management("Even")["posture"], "balanced")

    def test_slight_advantage_is_cautiously_safe(self):
        self.assertEqual(sa.compute_risk_management("Slight Advantage")["posture"], "cautiously_safe")

    def test_slight_disadvantage_is_cautiously_aggressive(self):
        self.assertEqual(sa.compute_risk_management("Slight Disadvantage")["posture"], "cautiously_aggressive")

    def test_unknown_label_falls_back_to_balanced(self):
        self.assertEqual(sa.compute_risk_management("Not A Real Band")["posture"], "balanced")


class TestBattleIntelligenceReportsWiredIntoTimeline(unittest.TestCase):
    """Integration coverage for task #226: build_momentum_timeline's new,
    ADDITIVE keys - proving they're present, internally consistent with each
    other, and that every pre-existing key (`score`, `delta`, etc.) is
    completely untouched by their presence."""

    def test_all_six_new_keys_present_on_every_turn(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Incineroar"], o_brought=["Metagross", "Whimsicott"]),
            _field_state(1, 10, 1, ["Sylveon", "Incineroar"], ["Metagross", "Whimsicott"], tailwind="player"),
            _field_state(1, 40, 2, ["Sylveon", "Incineroar"], ["Metagross", "Whimsicott"]),
        ]
        timeline = sa.build_momentum_timeline(events, 1)
        for entry in timeline:
            for key in ("speed_control", "threat_pressure", "resource_advantage",
                        "momentum", "position_score", "risk_management"):
                self.assertIn(key, entry)

    def test_pre_existing_keys_are_unaffected(self):
        """Same fixture/assertions as the pre-existing
        TestMomentumTimeline.test_score_drops_after_a_faint_reduces_alive_count
        - proves the new reports didn't change `score`'s own arithmetic."""
        events = [
            _team_preview(p_brought=["Sylveon", "Incineroar"], o_brought=["Metagross", "Whimsicott"]),
            _field_state(1, 10, 1, ["Sylveon", "Incineroar"], ["Metagross", "Whimsicott"]),
            _faint(1, 20, "player", "Incineroar"),
            _field_state(1, 40, 2, ["Sylveon"], ["Metagross", "Whimsicott"]),
        ]
        timeline = sa.build_momentum_timeline(events, 1)
        turn1, turn2 = timeline
        self.assertEqual(turn1["score"], 0)
        self.assertLess(turn2["score"], turn1["score"])
        self.assertEqual(turn2["delta"], turn2["score"] - turn1["score"])

    def test_position_score_value_equals_score_when_no_sub_signals_fire(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Incineroar"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon", "Incineroar"], ["Metagross"]),
        ]
        timeline = sa.build_momentum_timeline(events, 1)
        entry = timeline[0]
        self.assertEqual(entry["position_score"]["value"], entry["score"])

    def test_risk_management_posture_matches_position_score_label(self):
        events = [
            _team_preview(p_brought=["A", "B", "C"], o_brought=["X"]),
            _field_state(1, 10, 1, ["A", "B"], ["X"]),
        ]
        timeline = sa.build_momentum_timeline(events, 1)
        entry = timeline[0]
        expected_posture = sa.compute_risk_management(entry["position_score"]["label"])["posture"]
        self.assertEqual(entry["risk_management"]["posture"], expected_posture)

    def test_momentum_delta_matches_the_turns_own_delta(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Incineroar"], o_brought=["Metagross", "Whimsicott"]),
            _field_state(1, 10, 1, ["Sylveon", "Incineroar"], ["Metagross", "Whimsicott"]),
            _faint(1, 20, "player", "Incineroar"),
            _field_state(1, 40, 2, ["Sylveon"], ["Metagross", "Whimsicott"]),
        ]
        timeline = sa.build_momentum_timeline(events, 1)
        for entry in timeline:
            self.assertEqual(entry["momentum"]["delta"], entry["delta"])

    def test_momentum_flags_the_faint_as_own_pokemon_fainted(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Incineroar"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon", "Incineroar"], ["Metagross"]),
            _faint(1, 20, "player", "Incineroar"),
            _field_state(1, 40, 2, ["Sylveon"], ["Metagross"]),
        ]
        timeline = sa.build_momentum_timeline(events, 1)
        turn2_events = timeline[1]["momentum"]["events"]
        self.assertTrue(any(e["type"] == "own_pokemon_fainted" and e["side"] == "player" for e in turn2_events))

    def test_speed_tool_revealed_via_showdown_style_event_flows_through(self):
        events = [
            _team_preview(p_brought=["Regieleki"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Regieleki"], ["Metagross"]),
            _item_or_ability(1, 15, "player", "Regieleki", "item: Choice Scarf"),
            _field_state(1, 40, 2, ["Regieleki"], ["Metagross"]),
        ]
        timeline = sa.build_momentum_timeline(events, 1)
        # Not known yet on turn 1 (reflects state as of the START of the turn)
        self.assertEqual(timeline[0]["speed_control"]["score"], 0)
        # Known as of turn 2
        self.assertEqual(timeline[1]["speed_control"]["score"], sa.SPEED_TOOL_WEIGHT)

    def test_trick_room_setter_resolved_from_a_real_move_used_event(self):
        events = [
            _team_preview(p_brought=["Hatterene"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Hatterene"], ["Metagross"]),
            _move_named(1, 15, "player", "Hatterene", "Trick Room"),
            _field_state(1, 40, 2, ["Hatterene"], ["Metagross"], trick_room=True),
        ]
        timeline = sa.build_momentum_timeline(events, 1)
        factors = timeline[1]["speed_control"]["factors"]
        self.assertTrue(any("Player set it up" in f for f in factors))

    def test_resource_advantage_screens_flow_through(self):
        events = [
            _team_preview(p_brought=["Sylveon"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"], screens="player Reflect"),
        ]
        timeline = sa.build_momentum_timeline(events, 1)
        self.assertTrue(timeline[0]["resource_advantage"]["screens"]["player"])


if __name__ == "__main__":
    unittest.main()
