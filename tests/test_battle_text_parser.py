"""
Tests for battle_text_parser.py - the deterministic on-screen-text-to-event
parser built to replace vision-based inference for the part of the pipeline
that's actually just reading exact, unambiguous text (see the module's own
docstring and ARCHITECTURE_HANDOFF.md's OCR write-up for the full
reasoning). Every pattern here is grounded in a real or well-documented
Pokemon battle text string - several were directly observed and verified
against actual captured frames during this project's own testing (the
Staraptor fainting line, "It's super effective!", "Scrafty's Intimidate").

Pure regex/string logic, no OCR/video/network involved.

Run: py -m unittest tests.test_battle_text_parser -v   (from poc-starter/)
"""

import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import battle_text_parser as btp  # noqa: E402


class TestFainting(unittest.TestCase):
    def test_opponent_fainting_uses_the_opposing_prefix(self):
        """This exact line is what the real Charizard/Staraptor bug's frame
        actually showed on screen - see ARCHITECTURE_HANDOFF.md."""
        e = btp.parse_line("The opposing Staraptor fainted!")
        self.assertEqual(e["event"], "pokemon_fainted")
        self.assertEqual(e["pokemon"], "Staraptor")
        self.assertEqual(e["actor"], "opponent")
        self.assertEqual(e["hp_percent"], 0)

    def test_player_fainting_has_no_opposing_prefix(self):
        e = btp.parse_line("Greninja fainted!")
        self.assertEqual(e["event"], "pokemon_fainted")
        self.assertEqual(e["pokemon"], "Greninja")
        self.assertEqual(e["actor"], "player")

    def test_confidence_is_high_for_a_deterministic_text_match(self):
        """OCR-derived events should read as MORE trustworthy than a vision
        guess, not less - see LOW_CONFIDENCE_THRESHOLD in MatchEvents.jsx."""
        e = btp.parse_line("Greninja fainted!")
        self.assertGreaterEqual(e["confidence"], 0.9)


class TestEffectivenessAndCrits(unittest.TestCase):
    def test_super_effective(self):
        e = btp.parse_line("It's super effective!")
        self.assertEqual(e["event"], "super_effective_hit")

    def test_not_very_effective(self):
        e = btp.parse_line("It's not very effective...")
        self.assertEqual(e["event"], "not_very_effective_hit")

    def test_no_effect_names_the_immune_pokemon(self):
        e = btp.parse_line("It doesn't affect Ferrothorn...")
        self.assertEqual(e["event"], "not_very_effective_hit")
        self.assertEqual(e["pokemon"], "Ferrothorn")

    def test_critical_hit(self):
        e = btp.parse_line("A critical hit!")
        self.assertEqual(e["event"], "critical_hit")


class TestStatChanges(unittest.TestCase):
    """The trickiest ordering case in the whole module: a stat-change line
    ("X's Attack rose!") and an ability/item callout ("X's Intimidate")
    have the exact same "X's ..." shape - only the specific stat-change
    wording at the end distinguishes them. The stat-change pattern MUST be
    tried first or every stat change would get misread as an ability."""

    def test_plain_rise(self):
        e = btp.parse_line("Incineroar's Attack rose!")
        self.assertEqual(e["event"], "stat_change")
        self.assertEqual(e["pokemon"], "Incineroar")
        self.assertIn("Attack", e["detail"])

    def test_sharp_rise(self):
        e = btp.parse_line("Incineroar's Attack sharply rose!")
        self.assertEqual(e["event"], "stat_change")

    def test_capped_stat(self):
        e = btp.parse_line("Sylveon's Sp. Def won't go any higher!")
        self.assertEqual(e["event"], "stat_change")
        self.assertEqual(e["pokemon"], "Sylveon")

    def test_not_misread_as_ability_activation(self):
        e = btp.parse_line("Incineroar's Attack rose!")
        self.assertNotEqual(e["event"], "item_or_ability_activated")


class TestAbilityAndItemActivation(unittest.TestCase):
    def test_short_callout_form(self):
        """Exactly what a real captured frame showed during this project's
        testing - a bare "X's AbilityName" with no verb at all."""
        e = btp.parse_line("Scrafty's Intimidate")
        self.assertEqual(e["event"], "item_or_ability_activated")
        self.assertEqual(e["pokemon"], "Scrafty")
        self.assertEqual(e["detail"], "Intimidate")

    def test_explicit_activated_form(self):
        e = btp.parse_line("Charizard's Blaze activated!")
        self.assertEqual(e["event"], "item_or_ability_activated")
        self.assertEqual(e["pokemon"], "Charizard")

    def test_short_form_confidence_is_lower_than_explicit_form(self):
        """The bare "X's Y" shape is more easily confused with an
        unrelated possessive phrase this parser hasn't seen yet, so it's
        intentionally less confident than the unambiguous "activated" form."""
        short = btp.parse_line("Scrafty's Intimidate")
        explicit = btp.parse_line("Charizard's Blaze activated!")
        self.assertLess(short["confidence"], explicit["confidence"])


class TestStatusConditions(unittest.TestCase):
    def test_poisoned(self):
        e = btp.parse_line("Greninja was poisoned!")
        self.assertEqual(e["event"], "status_inflicted")
        self.assertEqual(e["pokemon"], "Greninja")

    def test_paralyzed(self):
        e = btp.parse_line("Metagross is paralyzed!")
        self.assertEqual(e["event"], "status_inflicted")


class TestMoveUsage(unittest.TestCase):
    def test_normal_move(self):
        e = btp.parse_line("Greninja used Hydro Pump!")
        self.assertEqual(e["event"], "move_used")
        self.assertEqual(e["pokemon"], "Greninja")
        self.assertEqual(e["detail"], "Hydro Pump")

    def test_failed_move_is_still_move_used_but_notes_the_failure(self):
        e = btp.parse_line("Metagross used Meteor Mash, but it failed!")
        self.assertEqual(e["event"], "move_used")
        self.assertEqual(e["pokemon"], "Metagross")
        self.assertIn("failed", e["detail"])

    def test_failed_move_has_slightly_lower_confidence(self):
        normal = btp.parse_line("Greninja used Hydro Pump!")
        failed = btp.parse_line("Metagross used Meteor Mash, but it failed!")
        self.assertLess(failed["confidence"], normal["confidence"])


class TestSendOut(unittest.TestCase):
    def test_go_exclamation_form(self):
        e = btp.parse_line("Go! Charizard!")
        self.assertEqual(e["event"], "pokemon_sent_out")
        self.assertEqual(e["pokemon"], "Charizard")
        self.assertEqual(e["actor"], "player")

    def test_go_comma_form(self):
        e = btp.parse_line("Go, Charizard!")
        self.assertEqual(e["event"], "pokemon_sent_out")
        self.assertEqual(e["pokemon"], "Charizard")

    def test_trainer_sent_out_form(self):
        e = btp.parse_line("FateTestarossaH sent out Primarina!")
        self.assertEqual(e["event"], "pokemon_sent_out")
        self.assertEqual(e["pokemon"], "Primarina")


class TestWeatherAndTerrain(unittest.TestCase):
    def test_rain(self):
        e = btp.parse_line("Rain began to fall!")
        self.assertEqual(e["event"], "weather_or_terrain_set")

    def test_sandstorm(self):
        e = btp.parse_line("The sandstorm rages.")
        self.assertEqual(e["event"], "weather_or_terrain_set")

    def test_electric_terrain(self):
        e = btp.parse_line("Electric Terrain surrounds the battlefield!")
        self.assertEqual(e["event"], "weather_or_terrain_set")


class TestBattleEnd(unittest.TestCase):
    def test_win(self):
        e = btp.parse_line("You won the battle!")
        self.assertEqual(e["event"], "battle_end")
        self.assertEqual(e["winner"], "player")

    def test_loss(self):
        e = btp.parse_line("You lost the battle!")
        self.assertEqual(e["event"], "battle_end")
        self.assertEqual(e["winner"], "opponent")


class TestUnrecognizedText(unittest.TestCase):
    def test_garbage_text_returns_none_not_a_guess(self):
        """The whole point of the None return is to signal 'fall back to
        vision for this moment' - it must never invent a plausible-looking
        but made-up event for text it doesn't actually recognize."""
        self.assertIsNone(btp.parse_line("complete garbage text xyz 123"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(btp.parse_line(""))
        self.assertIsNone(btp.parse_line("   "))

    def test_none_input_returns_none_not_a_crash(self):
        self.assertIsNone(btp.parse_line(None))


class TestEverySchemaFieldIsPresent(unittest.TestCase):
    """Every event this module returns must carry every field the shared
    Pokemon schema (adapters/pokemon/game.json + doubles.json) defines,
    even if null - downstream code (derive_brought, the dashboard) expects
    a consistent shape regardless of which event type produced it."""

    def test_all_expected_keys_present(self):
        expected_keys = {
            "event", "detail", "confidence", "pokemon", "actor", "hp_percent",
            "winner", "turn", "weather", "terrain", "trick_room", "tailwind",
            "screens", "field_status", "player_active", "opponent_active",
        }
        e = btp.parse_line("Greninja used Hydro Pump!")
        self.assertEqual(set(e.keys()), expected_keys)


class TestParseLines(unittest.TestCase):
    def test_splits_a_multiline_string_and_parses_each_line(self):
        blob = "Greninja used Hydro Pump!\nIt's super effective!\ngarbage\nCharizard fainted!"
        events = btp.parse_lines(blob)
        self.assertEqual([e["event"] for e in events],
                          ["move_used", "super_effective_hit", "pokemon_fainted"])

    def test_accepts_a_list_of_lines_too(self):
        events = btp.parse_lines(["A critical hit!", "not a real line"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "critical_hit")

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(btp.parse_lines(""), [])
        self.assertEqual(btp.parse_lines([]), [])


if __name__ == "__main__":
    unittest.main()
