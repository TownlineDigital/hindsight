"""
Regression tests for analyze_matches.py's species-legality allowlist and the
Mega/regional-form normalization it depends on.

Every case here is grounded in a REAL bug hit during development (see the
project chat history / backend/README_BACKEND.md "Data-quality fixes"), not a
hypothetical - the point of this file is to make sure none of them come back
silently the next time the allowlist or normalization logic changes:

  - Dragalge/Qwilfish were wrongly REJECTED (allowlist only had 6 of 22 real
    M-B additions confirmed) until the StrataDex/Serebii cross-check.
  - Alolan Ninetales was wrongly REJECTED (regional-form prefix wasn't
    stripped, only the suffix form was handled).
  - Mawile + Mawile (Mega) were wrongly counted as 2 separate team slots
    (Species Clause violation) before Mega-annotation stripping existed.
  - Fletchinder/Amoonguss/Ogerpon/Cradily/Dondozo/Porygon2/Drapion/Gastrodon
    were all real misreads that SHOULD be rejected - Pokemon Champions has a
    small closed roster, and these simply aren't in it.
  - A production crash (`TypeError` comparing None to str in `sorted()`)
    happened when a roster read contained a literal `None` entry.

Run: py -m unittest tests.test_species_legality -v   (from poc-starter/)
"""

import unittest

import analyze_matches as am


class TestAllowedSpecies(unittest.TestCase):

    def test_all_22_confirmed_mb_additions_are_legal(self):
        """The full, source-confirmed list from Serebii's official Regulation
        M-B "Newly Useable Pokemon" page - this is the exact set that was
        undercounted (only 6 of 22) when Dragalge/Qwilfish were wrongly
        rejected."""
        mb_additions = [
            "Metagross", "Mawile", "Grimmsnarl", "Sceptile", "Gholdengo", "Annihilape",
            "Eelektross", "Blaziken", "Swampert", "Staraptor", "Scolipede", "Scrafty",
            "Pyroar", "Malamar", "Barbaracle", "Dragalge", "Falinks", "Vileplume",
            "Qwilfish", "Musharna", "Overqwil", "Houndstone",
        ]
        rejected = am.flag_banned_species(mb_additions)
        self.assertEqual(rejected, [], f"These are confirmed-legal M-B additions, got wrongly rejected: {rejected}")

    def test_confirmed_ma_legal_species(self):
        """Toxicroak was flagged as a possible exception during development
        and the user confirmed it's actually legal - regression-guard that."""
        for name in ["Toxicroak", "Ninetales", "Incineroar", "Garchomp", "Whimsicott"]:
            with self.subTest(name=name):
                self.assertEqual(am.flag_banned_species([name]), [], f"{name} should be legal")

    def test_known_illegal_species_are_rejected(self):
        """Real misreads hit in production - none of these are in Champions'
        closed roster (Paradox/Legendary/Mythical/simply-not-added-yet)."""
        illegal = ["Fletchinder", "Amoonguss", "Ogerpon", "Cradily", "Dondozo",
                   "Porygon2", "Drapion", "Gastrodon", "Great Tusk", "Iron Hands"]
        for name in illegal:
            with self.subTest(name=name):
                self.assertEqual(am.flag_banned_species([name]), [name], f"{name} should be rejected as illegal")

    def test_flag_banned_species_skips_blank_entries(self):
        """A blank/None isn't an illegal species, just nothing read - it must
        never show up in the rejected list."""
        self.assertEqual(am.flag_banned_species([None, "", "Mawile"]), [])


class TestMegaAndRegionalNormalization(unittest.TestCase):

    def test_mega_prefix_and_suffix_forms_match_base_species(self):
        base = am._species_base_norm("Mawile")
        for variant in ["Mega Mawile", "Mawile (Mega)", "Mawile-Mega", "Mawile Mega"]:
            with self.subTest(variant=variant):
                self.assertEqual(am._species_base_norm(variant), base)

    def test_mega_x_y_suffix_forms_match_base_species(self):
        """Real gap found while building showdown_import.py: Pokemon Showdown's
        own notation writes X/Y Mega Evolutions as "Species-Mega-X"/
        "Species-Mega-Y" (e.g. "Charizard-Mega-Y") - the original suffix
        regex only stripped a bare trailing "-Mega", not "-Mega-X"/"-Mega-Y",
        so these would have wrongly failed to normalize to their base species."""
        base = am._species_base_norm("Charizard")
        for variant in ["Charizard-Mega-Y", "Charizard-Mega-X", "Charizard Mega Y"]:
            with self.subTest(variant=variant):
                self.assertEqual(am._species_base_norm(variant), base)

    def test_regional_prefix_and_suffix_forms_match_base_species(self):
        """The real bug: only the SUFFIX form ("Ninetales-Alola") was handled
        at first, so "Alolan Ninetales" (prefix form) was wrongly rejected."""
        base = am._species_base_norm("Ninetales")
        for variant in ["Alolan Ninetales", "Alolan  Ninetales", "Ninetales-Alola", "Ninetales Alolan"]:
            with self.subTest(variant=variant):
                self.assertEqual(am._species_base_norm(variant), base)

    def test_hyphenated_species_name_not_mangled(self):
        """Kommo-o has its own hyphen - normalization must not strip it as if
        it were a "-Mega"/"-Alola" suffix."""
        self.assertEqual(am._species_base_norm("Kommo-o"), am._norm("Kommo-o"))

    def test_species_clause_dedup_collapses_mega_to_one_slot(self):
        """The real bug: Mawile and Mawile (Mega) were counted as 2 separate
        brought Pokemon, a Species Clause violation that can't happen in a
        real match."""
        roster = {"player_team": ["Mawile", "Grimmsnarl", "Sceptile", "Metagross"]}
        events = [
            {"timestamp": 1, "event": "pokemon_sent_out", "actor": "player", "pokemon": "Mawile"},
            {"timestamp": 2, "event": "pokemon_sent_out", "actor": "player", "pokemon": "Grimmsnarl"},
            {"timestamp": 30, "event": "move_used", "actor": "player", "pokemon": "Mawile (Mega)"},
        ]
        brought, _, lead, _ = am.derive_brought(events, roster)
        self.assertEqual(brought.count("Mawile"), 1, f"Mawile should only count once, got: {brought}")


class TestRejectBannedSpecies(unittest.TestCase):

    def test_none_entries_do_not_crash_sorted(self):
        """Real production crash: TypeError comparing None to str inside
        sorted() when a roster read contained a literal None entry."""
        clean, rejected = am.reject_banned_species(["Mawile", None, "Gastrodon", ""])
        self.assertEqual(clean, ["Mawile"])
        self.assertEqual(rejected, ["Gastrodon"])

    def test_all_legal_returns_empty_rejected_list(self):
        clean, rejected = am.reject_banned_species(["Mawile", "Grimmsnarl"])
        self.assertEqual(clean, ["Mawile", "Grimmsnarl"])
        self.assertEqual(rejected, [])

    def test_bisharp_is_substituted_to_kingambit_not_rejected(self):
        """Real finding from a live A/B test on job 303d13ba0940 match 4:
        Bisharp isn't in Champions' roster at all, but its evolution
        Kingambit is - and the roster read's own model kept confidently
        writing "Bisharp" for a slot a human confirmed (via literal on-screen
        text) was Kingambit. Rather than silently dropping "Bisharp" as
        generic illegal noise, it should be corrected to the one legal
        species it's actually strong evidence for."""
        clean, rejected = am.reject_banned_species(["Bisharp", "Charizard"])
        self.assertEqual(clean, ["Kingambit", "Charizard"])
        self.assertEqual(rejected, [])

    def test_bisharp_substitution_is_case_insensitive(self):
        clean, rejected = am.reject_banned_species(["bisharp", "BISHARP"])
        self.assertEqual(clean, ["Kingambit", "Kingambit"])
        self.assertEqual(rejected, [])

    def test_substitution_does_not_affect_unrelated_illegal_species(self):
        """Only documented cut-pre-evolutions get substituted - an ordinary
        illegal/unrecognized name must still be rejected as before."""
        clean, rejected = am.reject_banned_species(["Bisharp", "Gastrodon"])
        self.assertEqual(clean, ["Kingambit"])
        self.assertEqual(rejected, ["Gastrodon"])


class TestMergeBrought(unittest.TestCase):
    """merge_brought() used to be a nested closure inside main()'s per-match
    loop - pulled out to a top-level function so both the live loop and
    batch mode (run_batch_mode) share one implementation instead of two
    copies that could quietly drift apart. Tested directly now that it's a
    real, independent function."""

    def test_tops_up_appearance_derived_with_directly_read_selection(self):
        """Appearance-derived brought under-counts when a chosen Pokemon
        never actually gets sent in (opponent conceded, wasn't needed) -
        the team-preview's own directly-read selection doesn't have that
        blind spot and should fill the gap."""
        derived = ["Mawile", "Grimmsnarl"]
        direct_raw = ["Mawile", "Grimmsnarl", "Sceptile", "Metagross"]
        brought, rejected = am.merge_brought(derived, direct_raw, {})
        self.assertEqual(brought, ["Mawile", "Grimmsnarl", "Sceptile", "Metagross"])
        self.assertEqual(rejected, [])

    def test_species_clause_guard_prevents_double_counting_a_mega(self):
        derived = ["Mawile"]
        direct_raw = ["Mawile (Mega)"]   # same species, already counted
        brought, rejected = am.merge_brought(derived, direct_raw, {})
        self.assertEqual(brought, ["Mawile"])

    def test_illegal_species_in_direct_read_gets_rejected_not_added(self):
        derived = ["Mawile"]
        direct_raw = ["Mawile", "Gastrodon"]   # Gastrodon isn't in the closed roster
        brought, rejected = am.merge_brought(derived, direct_raw, {})
        self.assertEqual(brought, ["Mawile"])
        self.assertEqual(rejected, ["Gastrodon"])

    def test_caps_at_four(self):
        derived = []
        direct_raw = ["Mawile", "Grimmsnarl", "Sceptile", "Metagross", "Gholdengo"]
        brought, rejected = am.merge_brought(derived, direct_raw, {})
        self.assertEqual(len(brought), 4)


if __name__ == "__main__":
    unittest.main()
