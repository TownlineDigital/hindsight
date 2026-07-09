"""
Tests for decision_windows.py - reconstructing, per turn, what each side had
available (board, alive roster, switch options, revealed-so-far moves) and
what it actually chose (move or switch), from one match's events.json entries.

Deliberately BEHAVIOR tests built around the module's own stated principles
(see its docstring): a turn's snapshot must reflect state as of the START of
that turn, never leaking that turn's own outcome back into what was
"available" going in; known_moves only ever contains moves already revealed
in an EARLIER turn; a match with no field_state/turn info returns [] rather
than fabricating turn numbers.

Run: py -m unittest tests.test_decision_windows -v   (from poc-starter/)
"""

import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import decision_windows as dw  # noqa: E402


def _team_preview(match=1, ts=0.0, p_brought=None, o_brought=None):
    return {
        "event": "team_preview", "match": match, "timestamp": ts, "actor": "both",
        "player_brought": ", ".join(p_brought or []),
        "opponent_brought": ", ".join(o_brought or []),
    }


def _field_state(match, ts, turn, p_active, o_active):
    return {
        "event": "field_state", "match": match, "timestamp": ts, "actor": "both",
        "turn": turn, "player_active": ", ".join(p_active), "opponent_active": ", ".join(o_active),
    }


def _move(match, ts, actor, pokemon, detail, move_field=None):
    e = {"event": "move_used", "match": match, "timestamp": ts, "actor": actor,
         "pokemon": pokemon, "detail": detail}
    if move_field:
        e["move"] = move_field
    return e


def _switch(match, ts, actor, pokemon):
    return {"event": "pokemon_sent_out", "match": match, "timestamp": ts, "actor": actor, "pokemon": pokemon}


def _faint(match, ts, actor, pokemon):
    return {"event": "pokemon_fainted", "match": match, "timestamp": ts, "actor": actor, "pokemon": pokemon}


class TestBasicWindowShape(unittest.TestCase):
    def test_one_window_per_turn_seen(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Incineroar"], o_brought=["Metagross", "Whimsicott"]),
            _field_state(1, 10, 1, ["Sylveon", "Incineroar"], ["Metagross", "Whimsicott"]),
            _move(1, 12, "player", "Sylveon", "Hyper Voice"),
            _field_state(1, 40, 2, ["Sylveon", "Incineroar"], ["Metagross", "Whimsicott"]),
            _move(1, 42, "player", "Sylveon", "Protect"),
        ]
        windows = dw.build_decision_windows(events, 1)
        self.assertEqual([w["turn"] for w in windows], [1, 2])
        self.assertTrue(all(w["match"] == 1 for w in windows))

    def test_board_reflects_active_pokemon_from_field_state(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Incineroar"], o_brought=["Metagross", "Whimsicott"]),
            _field_state(1, 10, 1, ["Sylveon", "Incineroar"], ["Metagross", "Whimsicott"]),
        ]
        windows = dw.build_decision_windows(events, 1)
        self.assertEqual(windows[0]["player"]["board"], ["Sylveon", "Incineroar"])
        self.assertEqual(windows[0]["opponent"]["board"], ["Metagross", "Whimsicott"])

    def test_available_pokemon_is_the_brought_list(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Incineroar", "Garchomp", "Corviknight"],
                          o_brought=["Metagross", "Whimsicott"]),
            _field_state(1, 10, 1, ["Sylveon", "Incineroar"], ["Metagross", "Whimsicott"]),
        ]
        windows = dw.build_decision_windows(events, 1)
        self.assertEqual(windows[0]["player"]["available_pokemon"],
                         ["Sylveon", "Incineroar", "Garchomp", "Corviknight"])

    def test_switch_options_excludes_current_board(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Incineroar", "Garchomp", "Corviknight"],
                          o_brought=["Metagross", "Whimsicott"]),
            _field_state(1, 10, 1, ["Sylveon", "Incineroar"], ["Metagross", "Whimsicott"]),
        ]
        windows = dw.build_decision_windows(events, 1)
        self.assertEqual(windows[0]["player"]["switch_options"], ["Garchomp", "Corviknight"])


class TestChosenActions(unittest.TestCase):
    def test_move_used_recorded_as_chosen_action(self):
        events = [
            _team_preview(p_brought=["Sylveon"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
            _move(1, 12, "player", "Sylveon", "Hyper Voice"),
        ]
        windows = dw.build_decision_windows(events, 1)
        self.assertEqual(windows[0]["player"]["chosen_actions"],
                         [{"type": "move", "pokemon": "Sylveon", "move": "Hyper Voice"}])

    def test_switch_recorded_as_chosen_action(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Garchomp"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
            _switch(1, 15, "player", "Garchomp"),
        ]
        windows = dw.build_decision_windows(events, 1)
        self.assertEqual(windows[0]["player"]["chosen_actions"],
                         [{"type": "switch", "pokemon": "Garchomp"}])

    def test_a_faint_is_not_itself_a_chosen_action(self):
        events = [
            _team_preview(p_brought=["Sylveon"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
            _faint(1, 20, "opponent", "Metagross"),
        ]
        windows = dw.build_decision_windows(events, 1)
        self.assertEqual(windows[0]["opponent"]["chosen_actions"], [])


class TestKnownMovesTiming(unittest.TestCase):
    """The core "information state" guarantee: a move only ever counts as
    known starting the turn AFTER it was used, never the same turn."""

    def test_move_not_known_during_the_turn_it_is_first_used(self):
        events = [
            _team_preview(p_brought=["Sylveon"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
            _move(1, 12, "player", "Sylveon", "Hyper Voice"),
        ]
        windows = dw.build_decision_windows(events, 1)
        self.assertEqual(windows[0]["player"]["known_moves"].get("Sylveon", []), [])

    def test_move_known_on_the_following_turn(self):
        events = [
            _team_preview(p_brought=["Sylveon"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
            _move(1, 12, "player", "Sylveon", "Hyper Voice"),
            _field_state(1, 40, 2, ["Sylveon"], ["Metagross"]),
        ]
        windows = dw.build_decision_windows(events, 1)
        self.assertEqual(windows[1]["player"]["known_moves"]["Sylveon"], ["Hyper Voice"])

    def test_moves_accumulate_across_turns_without_duplicates(self):
        events = [
            _team_preview(p_brought=["Sylveon"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
            _move(1, 12, "player", "Sylveon", "Hyper Voice"),
            _field_state(1, 40, 2, ["Sylveon"], ["Metagross"]),
            _move(1, 42, "player", "Sylveon", "Hyper Voice"),  # repeated move
            _field_state(1, 70, 3, ["Sylveon"], ["Metagross"]),
            _move(1, 72, "player", "Sylveon", "Protect"),
            _field_state(1, 100, 4, ["Sylveon"], ["Metagross"]),
        ]
        windows = dw.build_decision_windows(events, 1)
        turn4 = next(w for w in windows if w["turn"] == 4)
        self.assertEqual(turn4["player"]["known_moves"]["Sylveon"], ["Hyper Voice", "Protect"])

    def test_move_name_falls_back_to_detail_when_no_move_field(self):
        """See module docstring: no real code path populates a `move` field
        today - detail is what actually carries the move name."""
        events = [
            _team_preview(p_brought=["Sylveon"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
            _move(1, 12, "player", "Sylveon", "Hyper Voice"),  # no move_field
            _field_state(1, 40, 2, ["Sylveon"], ["Metagross"]),
        ]
        windows = dw.build_decision_windows(events, 1)
        self.assertEqual(windows[1]["player"]["known_moves"]["Sylveon"], ["Hyper Voice"])

    def test_structured_move_field_preferred_over_detail(self):
        events = [
            _team_preview(p_brought=["Sylveon"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
            _move(1, 12, "player", "Sylveon", "used a move!", move_field="Hyper Voice"),
            _field_state(1, 40, 2, ["Sylveon"], ["Metagross"]),
        ]
        windows = dw.build_decision_windows(events, 1)
        self.assertEqual(windows[1]["player"]["known_moves"]["Sylveon"], ["Hyper Voice"])

    def test_failed_move_still_counts_as_revealed_without_the_suffix(self):
        events = [
            _team_preview(p_brought=["Sylveon"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
            _move(1, 12, "player", "Sylveon", "Hyper Voice (failed)"),
            _field_state(1, 40, 2, ["Sylveon"], ["Metagross"]),
        ]
        windows = dw.build_decision_windows(events, 1)
        self.assertEqual(windows[1]["player"]["known_moves"]["Sylveon"], ["Hyper Voice"])


class TestFaintedTracking(unittest.TestCase):
    def test_fainted_pokemon_removed_from_available_and_switch_options_next_turn(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Incineroar"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
            _faint(1, 20, "player", "Incineroar"),
            _field_state(1, 40, 2, ["Sylveon"], ["Metagross"]),
        ]
        windows = dw.build_decision_windows(events, 1)
        turn1 = next(w for w in windows if w["turn"] == 1)
        turn2 = next(w for w in windows if w["turn"] == 2)
        # Incineroar fainted DURING turn 1, so it was still "available" going in...
        self.assertIn("Incineroar", turn1["player"]["available_pokemon"])
        # ...but gone from turn 2's snapshot.
        self.assertNotIn("Incineroar", turn2["player"]["available_pokemon"])
        self.assertNotIn("Incineroar", turn2["player"]["switch_options"])


class TestSwitchesUpdateNextTurnsBoard(unittest.TestCase):
    def test_switch_recorded_this_turn_shows_on_board_next_turn(self):
        events = [
            _team_preview(p_brought=["Sylveon", "Garchomp"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
            _switch(1, 15, "player", "Garchomp"),
            # No field_state for turn 2 updating player_active - board should
            # still reflect the switch via the pokemon_sent_out fallback.
        ]
        events.append({"event": "field_state", "match": 1, "timestamp": 40,
                       "actor": "both", "turn": 2, "player_active": "", "opponent_active": "Metagross"})
        windows = dw.build_decision_windows(events, 1)
        turn2 = next(w for w in windows if w["turn"] == 2)
        self.assertIn("Garchomp", turn2["player"]["board"])


class TestNoTurnInfo(unittest.TestCase):
    def test_returns_empty_list_with_no_field_state_events(self):
        """A Showdown-imported match today has no field_state/turn events at
        all - nothing to key turns off, so this must not fabricate turn
        numbers (see module docstring)."""
        events = [
            _team_preview(p_brought=["Sylveon"], o_brought=["Metagross"]),
            _move(1, 12, "player", "Sylveon", "Hyper Voice"),
            _faint(1, 240, "opponent", "Metagross"),
        ]
        windows = dw.build_decision_windows(events, 1)
        self.assertEqual(windows, [])

    def test_returns_empty_list_for_totally_empty_events(self):
        self.assertEqual(dw.build_decision_windows([], 1), [])


class TestWholeJobMultiMatch(unittest.TestCase):
    def test_separates_windows_per_match(self):
        events = [
            _team_preview(match=1, p_brought=["Sylveon"], o_brought=["Metagross"]),
            _field_state(1, 10, 1, ["Sylveon"], ["Metagross"]),
            _move(1, 12, "player", "Sylveon", "Hyper Voice"),
            _team_preview(match=2, ts=300, p_brought=["Garchomp"], o_brought=["Whimsicott"]),
            _field_state(2, 310, 1, ["Garchomp"], ["Whimsicott"]),
            _move(2, 312, "player", "Garchomp", "Earthquake"),
        ]
        windows = dw.build_decision_windows_for_job(events)
        matches_seen = sorted({w["match"] for w in windows})
        self.assertEqual(matches_seen, [1, 2])
        match1 = [w for w in windows if w["match"] == 1]
        match2 = [w for w in windows if w["match"] == 2]
        self.assertEqual(match1[0]["player"]["chosen_actions"][0]["pokemon"], "Sylveon")
        self.assertEqual(match2[0]["player"]["chosen_actions"][0]["pokemon"], "Garchomp")

    def test_works_without_a_match_field_via_team_preview_segmentation(self):
        """group_by_match()'s fallback path (no `match` field anywhere)
        segments at each team_preview - build_decision_windows_for_job must
        still produce correct, separated windows in that case (see its own
        docstring about stamping `match` before delegating)."""
        events = [
            {"event": "team_preview", "timestamp": 0, "actor": "both",
             "player_brought": "Sylveon", "opponent_brought": "Metagross"},
            {"event": "field_state", "timestamp": 10, "actor": "both", "turn": 1,
             "player_active": "Sylveon", "opponent_active": "Metagross"},
            {"event": "move_used", "timestamp": 12, "actor": "player",
             "pokemon": "Sylveon", "detail": "Hyper Voice"},
            {"event": "team_preview", "timestamp": 300, "actor": "both",
             "player_brought": "Garchomp", "opponent_brought": "Whimsicott"},
            {"event": "field_state", "timestamp": 310, "actor": "both", "turn": 1,
             "player_active": "Garchomp", "opponent_active": "Whimsicott"},
        ]
        windows = dw.build_decision_windows_for_job(events)
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0]["player"]["board"], ["Sylveon"])
        self.assertEqual(windows[1]["player"]["board"], ["Garchomp"])


class TestNormalizeTurn(unittest.TestCase):
    """_normalize_turn() (added 2026-07-09) - the single choke point every
    turn-keyed helper here (and strategic_analysis.py) reads a raw `turn`
    value through. Real footage from job 303d13ba0940 mixed int turn values
    with numeric-string ("1") and literal "unknown" turn values in the SAME
    match, which crashed order.sort() with a str/int comparison TypeError
    before this existed - see the function's own docstring for the full
    story."""

    def test_int_passes_through_unchanged(self):
        self.assertEqual(dw._normalize_turn(3), 3)

    def test_numeric_string_is_coerced_to_int(self):
        self.assertEqual(dw._normalize_turn("1"), 1)

    def test_numeric_string_with_surrounding_whitespace_is_coerced(self):
        self.assertEqual(dw._normalize_turn("  7  "), 7)

    def test_the_literal_string_unknown_is_treated_as_missing(self):
        self.assertIsNone(dw._normalize_turn("unknown"))

    def test_none_is_treated_as_missing(self):
        self.assertIsNone(dw._normalize_turn(None))

    def test_bool_is_not_mistaken_for_an_int_turn_number(self):
        # bool is a subclass of int in Python - True/False must not silently
        # become turn 1/0.
        self.assertIsNone(dw._normalize_turn(True))
        self.assertIsNone(dw._normalize_turn(False))

    def test_non_integer_float_is_treated_as_missing(self):
        self.assertIsNone(dw._normalize_turn(1.5))

    def test_integer_valued_float_is_coerced(self):
        self.assertEqual(dw._normalize_turn(2.0), 2)

    def test_mixed_int_and_numeric_string_turns_do_not_crash_build_decision_windows(self):
        """The real regression: a match whose field_state events mix a raw
        int turn with a numeric-string turn used to crash
        build_decision_windows' own order.sort() - now both normalize to the
        same int and merge into one turn's window instead of two."""
        events = [
            _team_preview(p_brought=["Sylveon"], o_brought=["Metagross"]),
            {"event": "field_state", "match": 1, "timestamp": 10, "actor": "both",
             "turn": 1, "player_active": "Sylveon", "opponent_active": "Metagross"},
            _move(1, 12, "player", "Sylveon", "Hyper Voice"),
            {"event": "field_state", "match": 1, "timestamp": 20, "actor": "both",
             "turn": "2", "player_active": "Sylveon", "opponent_active": "Metagross"},
            _move(1, 22, "player", "Sylveon", "Protect"),
        ]
        windows = dw.build_decision_windows(events, 1)  # must not raise
        self.assertEqual([w["turn"] for w in windows], [1, 2])

    def test_a_literal_unknown_turn_is_skipped_rather_than_crashing(self):
        events = [
            _team_preview(p_brought=["Sylveon"], o_brought=["Metagross"]),
            {"event": "field_state", "match": 1, "timestamp": 10, "actor": "both",
             "turn": "unknown", "player_active": "Sylveon", "opponent_active": "Metagross"},
            {"event": "field_state", "match": 1, "timestamp": 20, "actor": "both",
             "turn": 1, "player_active": "Sylveon", "opponent_active": "Metagross"},
        ]
        windows = dw.build_decision_windows(events, 1)  # must not raise
        self.assertEqual([w["turn"] for w in windows], [1])


if __name__ == "__main__":
    unittest.main()
