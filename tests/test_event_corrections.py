"""
Tests for backend/event_corrections.py's cascading Pokemon-identity fix -
see that module's docstring for the problem this solves (fixing ONE misread
event shouldn't leave every other occurrence of the same wrong name still
wrong across the same match).
"""

import unittest

from backend.event_corrections import cascade_pokemon_correction


def _events():
    """A small, representative slice of one match's events.json: a
    misread "Charminion" recurring across a flat pokemon field, a
    field_state's comma-joined player_active string, a team_preview's
    comma-joined player_team/player_brought/player_lead strings, and a
    nested field_status entry - plus a few things that must NOT be
    touched: the same name on the opponent's side, the same name in a
    DIFFERENT match, and an unrelated Pokemon."""
    return [
        {"match": 1, "event": "team_preview", "actor": "both",
         "player_team": "Charminion, Whimsicott, Garchomp",
         "opponent_team": "Pelipper, Duraludon",
         "player_brought": "Charminion, Whimsicott",
         "opponent_brought": "Pelipper, Duraludon",
         "player_lead": "Charminion, Whimsicott",
         "opponent_lead": "Pelipper, Duraludon"},
        {"match": 1, "event": "move_used", "actor": "player", "pokemon": "Charminion", "detail": "Flamethrower"},
        {"match": 1, "event": "item_or_ability_activated", "actor": "player", "pokemon": "Charminion",
         "detail": "Mega Evolution"},
        {"match": 1, "event": "move_used", "actor": "player", "pokemon": "Whimsicott", "detail": "Tailwind"},
        {"match": 1, "event": "field_state", "player_active": "Charminion, Whimsicott",
         "opponent_active": "Pelipper, Duraludon"},
        {"match": 1, "event": "field_state",
         "field_status": {"opponent_active": [{"pokemon": "Pelipper", "status": "Defense fell"}],
                           "player_active": [{"pokemon": "Charminion", "status": "Burned"}]}},
        # Different match - must never be touched even though the name matches.
        {"match": 2, "event": "move_used", "actor": "player", "pokemon": "Charminion", "detail": "Flamethrower"},
        # Opponent's side, same match - must never be touched.
        {"match": 1, "event": "move_used", "actor": "opponent", "pokemon": "Charminion", "detail": "Flamethrower"},
    ]


class TestCascadePokemonCorrection(unittest.TestCase):
    def test_fixes_flat_pokemon_field_on_same_side_same_match(self):
        events = _events()
        touched = cascade_pokemon_correction(events, match=1, actor="player",
                                             old_name="Charminion", new_name="Charizard")
        self.assertIn(1, touched)   # move_used
        self.assertIn(2, touched)   # item_or_ability_activated
        self.assertEqual(events[1]["pokemon"], "Charizard")
        self.assertEqual(events[2]["pokemon"], "Charizard")

    def test_does_not_touch_a_different_match(self):
        events = _events()
        cascade_pokemon_correction(events, match=1, actor="player",
                                   old_name="Charminion", new_name="Charizard")
        self.assertEqual(events[6]["pokemon"], "Charminion")   # match=2, untouched

    def test_does_not_touch_the_opponents_side(self):
        events = _events()
        cascade_pokemon_correction(events, match=1, actor="player",
                                   old_name="Charminion", new_name="Charizard")
        self.assertEqual(events[7]["pokemon"], "Charminion")   # actor=opponent, untouched

    def test_does_not_touch_unrelated_pokemon(self):
        events = _events()
        cascade_pokemon_correction(events, match=1, actor="player",
                                   old_name="Charminion", new_name="Charizard")
        self.assertEqual(events[3]["pokemon"], "Whimsicott")   # untouched

    def test_fixes_comma_joined_player_active_string_exact_token_only(self):
        events = _events()
        cascade_pokemon_correction(events, match=1, actor="player",
                                   old_name="Charminion", new_name="Charizard")
        self.assertEqual(events[4]["player_active"], "Charizard, Whimsicott")
        self.assertEqual(events[4]["opponent_active"], "Pelipper, Duraludon")   # untouched

    def test_fixes_team_preview_comma_joined_fields_on_correct_side_only(self):
        events = _events()
        cascade_pokemon_correction(events, match=1, actor="player",
                                   old_name="Charminion", new_name="Charizard")
        self.assertEqual(events[0]["player_team"], "Charizard, Whimsicott, Garchomp")
        self.assertEqual(events[0]["player_brought"], "Charizard, Whimsicott")
        self.assertEqual(events[0]["player_lead"], "Charizard, Whimsicott")
        self.assertEqual(events[0]["opponent_team"], "Pelipper, Duraludon")   # untouched

    def test_fixes_nested_field_status_entry_on_correct_side_only(self):
        events = _events()
        cascade_pokemon_correction(events, match=1, actor="player",
                                   old_name="Charminion", new_name="Charizard")
        self.assertEqual(events[5]["field_status"]["player_active"][0]["pokemon"], "Charizard")
        self.assertEqual(events[5]["field_status"]["opponent_active"][0]["pokemon"], "Pelipper")

    def test_marks_every_touched_event_corrected(self):
        events = _events()
        touched = cascade_pokemon_correction(events, match=1, actor="player",
                                             old_name="Charminion", new_name="Charizard")
        for i in touched:
            self.assertTrue(events[i]["corrected"])

    def test_actor_both_does_not_cascade(self):
        """A "both"/missing actor means there's no reliable side to scope
        the cascade to - must no-op rather than guess."""
        events = _events()
        touched = cascade_pokemon_correction(events, match=1, actor="both",
                                             old_name="Charminion", new_name="Charizard")
        self.assertEqual(touched, [])

    def test_missing_actor_does_not_cascade(self):
        events = _events()
        touched = cascade_pokemon_correction(events, match=1, actor=None,
                                             old_name="Charminion", new_name="Charizard")
        self.assertEqual(touched, [])

    def test_same_old_and_new_name_is_a_noop(self):
        events = _events()
        touched = cascade_pokemon_correction(events, match=1, actor="player",
                                             old_name="Charminion", new_name="Charminion")
        self.assertEqual(touched, [])

    def test_falsy_old_name_is_a_noop(self):
        events = _events()
        touched = cascade_pokemon_correction(events, match=1, actor="player",
                                             old_name="", new_name="Charizard")
        self.assertEqual(touched, [])

    def test_returns_empty_list_when_nothing_matches(self):
        events = _events()
        touched = cascade_pokemon_correction(events, match=1, actor="player",
                                             old_name="Nonexistentmon", new_name="Charizard")
        self.assertEqual(touched, [])


if __name__ == "__main__":
    unittest.main()
