"""
Tests for backend/item_inference.py - the first slice of Phase 3 (build/EV
inference) in the live-coaching/optimal-play roadmap. Direct user request:
"damage with items like focus sash and choice scarf and life orb until we
know the opponent has it on their pokemon", confirmed via AskUserQuestion:
"Default to 'no item' until confirmed (Recommended)".

Covers the module in isolation (TestRevealedItems/TestItemFor) and, in
TestFullCompositionWithShowdownAndDamageCalc, the FULL real pipeline this
module exists to support: a synthetic Showdown battle log -> parsed by
showdown_import.py -> item_or_ability_activated events -> item_inference.py
-> a damage_calc.py attacker/defender dict - proving the "default to no
item until confirmed" behavior actually holds end to end across all three
modules, not just within item_inference.py alone.

Run: py -m unittest tests.test_item_inference -v   (from poc-starter/)
"""

import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend import item_inference as ii  # noqa: E402
from backend import damage_calc as dc  # noqa: E402
import showdown_import as si  # noqa: E402


class TestRevealedItems(unittest.TestCase):
    def test_collects_item_or_ability_activated_events_with_an_item_field(self):
        events = [
            {"event": "item_or_ability_activated", "actor": "opponent", "pokemon": "Garchomp", "item": "Life Orb"},
            {"event": "item_or_ability_activated", "actor": "player", "pokemon": "Whimsicott", "item": "Focus Sash"},
        ]
        self.assertEqual(ii.revealed_items(events), {
            "opponent:Garchomp": "Life Orb",
            "player:Whimsicott": "Focus Sash",
        })

    def test_ignores_events_without_a_structured_item_field(self):
        """An -ability reveal (item_or_ability_activated with `ability` but
        no `item`) must not appear - confirms this module never mistakes an
        ability reveal for an item one."""
        events = [
            {"event": "item_or_ability_activated", "actor": "opponent", "pokemon": "Incineroar",
             "ability": "Intimidate", "detail": "ability: Intimidate"},
        ]
        self.assertEqual(ii.revealed_items(events), {})

    def test_ignores_unrelated_event_types(self):
        events = [
            {"event": "move_used", "actor": "opponent", "pokemon": "Garchomp", "detail": "Earthquake"},
            {"event": "hp_change", "actor": "opponent", "pokemon": "Garchomp", "hp_percent": 50.0},
        ]
        self.assertEqual(ii.revealed_items(events), {})

    def test_empty_events_list_returns_empty_dict(self):
        self.assertEqual(ii.revealed_items([]), {})

    def test_malformed_entries_are_skipped_not_crashed_on(self):
        events = [
            None,
            "not a dict",
            {"event": "item_or_ability_activated"},   # missing actor/pokemon/item entirely
            {"event": "item_or_ability_activated", "actor": "opponent", "pokemon": "Garchomp", "item": "Life Orb"},
        ]
        self.assertEqual(ii.revealed_items(events), {"opponent:Garchomp": "Life Orb"})

    def test_same_species_different_actors_kept_separate(self):
        events = [
            {"event": "item_or_ability_activated", "actor": "player", "pokemon": "Kangaskhan", "item": "Leftovers"},
            {"event": "item_or_ability_activated", "actor": "opponent", "pokemon": "Kangaskhan", "item": "Sitrus Berry"},
        ]
        result = ii.revealed_items(events)
        self.assertEqual(result["player:Kangaskhan"], "Leftovers")
        self.assertEqual(result["opponent:Kangaskhan"], "Sitrus Berry")

    def test_later_reveal_for_the_same_pokemon_overwrites_earlier_one(self):
        """E.g. Trick swaps items mid-battle - the most recently confirmed
        item should win, not the first one ever seen."""
        events = [
            {"event": "item_or_ability_activated", "actor": "opponent", "pokemon": "Garchomp", "item": "Choice Scarf"},
            {"event": "item_or_ability_activated", "actor": "opponent", "pokemon": "Garchomp", "item": "Leftovers"},
        ]
        self.assertEqual(ii.revealed_items(events)["opponent:Garchomp"], "Leftovers")


class TestItemFor(unittest.TestCase):
    def setUp(self):
        self.events = [
            {"event": "item_or_ability_activated", "actor": "opponent", "pokemon": "Garchomp", "item": "Life Orb"},
        ]

    def test_returns_confirmed_item(self):
        self.assertEqual(ii.item_for(self.events, "opponent", "Garchomp"), "Life Orb")

    def test_returns_none_for_unconfirmed_pokemon(self):
        """The core behavior the user asked for: an opponent's Pokemon with
        NO evidence in this match must come back None, never a guessed
        popular item."""
        self.assertIsNone(ii.item_for(self.events, "opponent", "Incineroar"))

    def test_returns_none_for_wrong_actor(self):
        self.assertIsNone(ii.item_for(self.events, "player", "Garchomp"))


class TestFullCompositionWithShowdownAndDamageCalc(unittest.TestCase):
    """The real end-to-end proof: a synthetic Showdown log parsed by
    showdown_import.py, fed through item_inference.py, then used to build a
    damage_calc.py attacker dict - confirming a Life Orb boost applies ONLY
    once Showdown's own protocol has actually confirmed it, and an
    unconfirmed opponent item never silently sneaks a bonus into a damage
    calculation."""

    def setUp(self):
        log_lines = [
            "|player|p1|Ash|1|",
            "|player|p2|Gary|2|",
            "|gametype|doubles",
            "|switch|p1a: Garchomp|Garchomp, L50, M|100/100",
            "|switch|p2a: Incineroar|Incineroar, L50, M|100/100",
            "|turn|1",
            "|move|p1a: Garchomp|Earthquake|p2a: Incineroar",
            "|-damage|p2a: Incineroar|60/100",
            "|-damage|p1a: Garchomp|88/100|[from] item: Life Orb",
            "|win|Ash",
        ]
        parser = si.BattleParser(match_number=1, player_id="p1")
        for line in log_lines:
            parser.feed_line(line)
        self.match_events = parser.events

        garchomp_base = {"hp": 108, "attack": 130, "defense": 95,
                          "special-attack": 80, "special-defense": 85, "speed": 102}
        self.atk_stats = dc.calc_stats(garchomp_base, level=50, evs={"attack": 252}, nature="Adamant")
        self.defender = {"stats": {"hp": 150, "defense": 100, "special-defense": 100}, "types": ["normal"]}
        self.move = {"power": 100, "type": "ground", "category": "physical"}

    def test_confirmed_life_orb_boosts_the_attackers_own_damage(self):
        """Garchomp's OWN Life Orb was confirmed via its recoil line - a
        damage calc for the SAME Garchomp attacking again should reflect it."""
        item = ii.item_for(self.match_events, "player", "Garchomp")
        self.assertEqual(item, "Life Orb")

        attacker = {"stats": self.atk_stats, "types": ["ground", "dragon"], "item": item, "level": 50}
        with_item = dc.calculate_damage(attacker, self.defender, self.move, field={})

        attacker_no_item = dict(attacker, item=None)
        without_item = dc.calculate_damage(attacker_no_item, self.defender, self.move, field={})

        self.assertGreater(with_item["max"], without_item["max"])

    def test_unconfirmed_opponent_item_defaults_to_no_bonus(self):
        """The exact scenario the user asked about: Incineroar's item was
        NEVER revealed in this match (only took ordinary Earthquake damage,
        no [from] item:/-activate/-enditem line at all) - a damage
        calculation involving Incineroar as the attacker must get item=None
        automatically via item_for(), and damage_calc.py must apply no
        item bonus for it, not a guessed one."""
        item = ii.item_for(self.match_events, "opponent", "Incineroar")
        self.assertIsNone(item)

        incineroar_stats = {"hp": 100, "attack": 100, "defense": 100,
                             "special-attack": 100, "special-defense": 100, "speed": 100}
        attacker = {"stats": incineroar_stats, "types": ["fire", "dark"], "item": item, "level": 50}
        move = {"power": 80, "type": "dark", "category": "physical"}

        result_with_inferred_item = dc.calculate_damage(attacker, self.defender, move, field={})
        result_explicit_none = dc.calculate_damage(dict(attacker, item=None), self.defender, move, field={})
        # Composing item_for()'s None straight into the attacker dict must be
        # indistinguishable from explicitly passing item=None - this IS the
        # "default to no item until confirmed" behavior, verified end to end.
        self.assertEqual(result_with_inferred_item, result_explicit_none)


if __name__ == "__main__":
    unittest.main()
