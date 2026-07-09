"""
Tests for compose_schema.py's regulation layer (adapters/pokemon/regulations/
<id>.json) - added so the user can pick which Pokemon Champions regulation
(M-A/M-B) a job is analyzed against, instead of the roster/mechanics being
permanently hardcoded to whatever the current regulation happens to be. See
ARCHITECTURE_HANDOFF.md section 3a for the full design.

Runs against the REAL adapters/ directory in this repo (not synthetic fixtures) -
this is the same pattern test_species_legality.py already uses for validating
real regulation data, and there's real value in these tests failing if the
actual m-a.json/m-b.json/doubles.json/singles.json files ever get corrupted or
drift out of sync with each other.

Run: py -m unittest tests.test_compose_schema_regulation -v   (from poc-starter/)
"""

import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import compose_schema as cs  # noqa: E402

ADAPTERS = os.path.join(BASE_DIR, "adapters")


class TestRegulationIsOptional(unittest.TestCase):
    """A game/mode with no regulation concept (or a caller that just doesn't
    pass one) must compose exactly as it did before this feature existed -
    regulation is additive, never required."""

    def test_no_regulation_composes_without_error(self):
        schema = cs.compose(ADAPTERS, "pokemon", "doubles", None)
        self.assertNotIn("regulation", schema["rules"])

    def test_no_regulation_composed_from_has_no_regulation_layer(self):
        schema = cs.compose(ADAPTERS, "pokemon", "doubles", None)
        self.assertEqual(schema["_composed_from"],
                          ["_core", "pokemon/game", "pokemon/doubles"])

    def test_blank_string_regulation_treated_same_as_none(self):
        """main()'s CLI passes args.regulation or None - an empty --regulation
        flag value must not try to load a file literally named '.json'."""
        schema = cs.compose(ADAPTERS, "pokemon", "doubles", "")
        self.assertNotIn("regulation", schema["rules"])


class TestRegulationLayerMerges(unittest.TestCase):
    def test_mb_regulation_adds_legal_mechanics_to_rules(self):
        schema = cs.compose(ADAPTERS, "pokemon", "doubles", "m-b")
        self.assertEqual(schema["rules"]["regulation"], "M-B")
        self.assertTrue(schema["rules"]["mega_evolution"])
        self.assertFalse(schema["rules"]["dynamax"])
        self.assertFalse(schema["rules"]["terastallization"])

    def test_composed_from_records_the_regulation_layer(self):
        schema = cs.compose(ADAPTERS, "pokemon", "doubles", "m-b")
        self.assertIn("pokemon/regulations/m-b", schema["_composed_from"])

    def test_mode_level_rules_survive_alongside_regulation_rules(self):
        """Regulation adds/overrides its own keys - it must not wipe out the
        mode-generic rules (active_per_side, bring_count, ...) doubles.json
        still owns."""
        schema = cs.compose(ADAPTERS, "pokemon", "doubles", "m-b")
        self.assertEqual(schema["rules"]["active_per_side"], 2)
        self.assertEqual(schema["rules"]["bring_count"], 4)

    def test_regulation_format_notes_appear_in_notes_for_the_ai(self):
        schema = cs.compose(ADAPTERS, "pokemon", "doubles", "m-b")
        self.assertIn("Regulation M-B", schema["notes_for_the_ai"])

    def test_ma_and_mb_produce_different_regulation_metadata(self):
        """The whole point of this feature - selecting a different regulation
        must actually change what gets composed, not just accept-and-ignore
        the flag."""
        mb = cs.compose(ADAPTERS, "pokemon", "doubles", "m-b")
        ma = cs.compose(ADAPTERS, "pokemon", "doubles", "m-a")
        self.assertNotEqual(mb["rules"]["regulation"], ma["rules"]["regulation"])
        self.assertNotEqual(mb["rules"]["regulation_active_until"],
                            ma["rules"]["regulation_active_until"])

    def test_unknown_regulation_exits_with_a_clear_message(self):
        with self.assertRaises(SystemExit) as ctx:
            cs.compose(ADAPTERS, "pokemon", "doubles", "z-9-doesnt-exist")
        self.assertIn("Unknown regulation", str(ctx.exception))


class TestSinglesModeHasItsOwnRules(unittest.TestCase):
    """Singles was added as a real, distinct mode selector alongside doubles -
    it must carry its own (different) rules, not silently reuse doubles'."""

    def test_singles_has_no_fixed_bring_count(self):
        schema = cs.compose(ADAPTERS, "pokemon", "singles", "m-b")
        self.assertIsNone(schema["rules"]["bring_count"])
        self.assertEqual(schema["rules"]["active_per_side"], 1)

    def test_singles_and_doubles_compose_different_rules(self):
        singles = cs.compose(ADAPTERS, "pokemon", "singles", "m-b")
        doubles = cs.compose(ADAPTERS, "pokemon", "doubles", "m-b")
        self.assertNotEqual(singles["rules"]["active_per_side"],
                            doubles["rules"]["active_per_side"])

    def test_singles_still_gets_the_same_regulation_species_legality_facts(self):
        """Mode and regulation are independent axes - the SAME M-B roster/
        mechanics facts should apply regardless of which mode was chosen."""
        singles = cs.compose(ADAPTERS, "pokemon", "singles", "m-b")
        doubles = cs.compose(ADAPTERS, "pokemon", "doubles", "m-b")
        self.assertEqual(singles["rules"]["regulation"], doubles["rules"]["regulation"])
        self.assertEqual(singles["rules"]["mega_evolution"], doubles["rules"]["mega_evolution"])


class TestListAvailableIncludesRegulations(unittest.TestCase):
    def test_list_available_runs_without_error_and_finds_regulations(self):
        """Just confirms list_available() doesn't crash walking the new
        regulations/ subfolder - its output is printed, not returned, so
        this is a smoke test rather than a value assertion."""
        cs.list_available(ADAPTERS)  # would raise if the new code path broke


if __name__ == "__main__":
    unittest.main()
