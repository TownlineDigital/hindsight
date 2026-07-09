"""
Tests for accuracy_addons/tools/fetch_species_sprites.py - the standalone
script (not run by analyze_matches.py itself) that downloads Pokemon
Champions' actual menusprite icons (normal AND shiny) from Bulbagarden
Archives as a future icon-matcher's reference template library (see that
script's own docstring and ARCHITECTURE_HANDOFF.md).

These tests exercise only the pure, offline logic (filename parsing, the
static dex-number map) - NOT the actual network fetch, which needs real
internet access this test suite shouldn't depend on. `list_category_files`/
`list_all_category_files`/`download_file`/`main` are intentionally not
covered here for that reason.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "accuracy_addons", "tools"))
import fetch_species_sprites as fss  # noqa: E402


class TestNormalizeTitle(unittest.TestCase):
    """Regression coverage for a real bug: a live run against the actual
    Bulbagarden category (359 files) parsed ZERO of them, because
    MediaWiki's API returns titles with plain spaces ("Menu CP 0003.png"),
    not the underscore form ("Menu_CP_0003.png") FILENAME_RE expects -
    parse_filename silently returned None for every single title, so
    nothing was ever downloaded. normalize_title() fixes this by converting
    every space to an underscore before anything else touches the title
    (list_category_files calls it on every title it collects)."""

    def test_converts_spaces_to_underscores(self):
        self.assertEqual(fss.normalize_title("Menu CP 0003-Mega.png"), "Menu_CP_0003-Mega.png")

    def test_multi_word_form_suffix(self):
        self.assertEqual(fss.normalize_title("Menu CP 0666-High Plains.png"),
                          "Menu_CP_0666-High_Plains.png")

    def test_already_underscored_title_is_a_no_op(self):
        self.assertEqual(fss.normalize_title("Menu_CP_0006.png"), "Menu_CP_0006.png")

    def test_normalized_title_then_parses_correctly(self):
        """The actual end-to-end regression: normalize then parse should
        recover a valid (dex_number, form, shiny) tuple from a raw,
        space-separated MediaWiki title - this is exactly what failed in
        the real run."""
        raw_title = "Menu CP 0006-Mega X.png"
        parsed = fss.parse_filename(fss.normalize_title(raw_title))
        self.assertEqual(parsed, (6, "Mega_X", False))


class TestParseFilename(unittest.TestCase):

    def test_base_form_no_suffix(self):
        self.assertEqual(fss.parse_filename("Menu_CP_0006.png"), (6, None, False))

    def test_simple_form_suffix(self):
        self.assertEqual(fss.parse_filename("Menu_CP_0059-Hisui.png"), (59, "Hisui", False))

    def test_underscore_within_form_suffix(self):
        self.assertEqual(fss.parse_filename("Menu_CP_0128-Paldea_Aqua.png"), (128, "Paldea_Aqua", False))

    def test_mega_x_y_suffixes(self):
        self.assertEqual(fss.parse_filename("Menu_CP_0006-Mega_X.png"), (6, "Mega_X", False))
        self.assertEqual(fss.parse_filename("Menu_CP_0006-Mega_Y.png"), (6, "Mega_Y", False))

    def test_four_digit_dex_number_over_999(self):
        self.assertEqual(fss.parse_filename("Menu_CP_1019.png"), (1019, None, False))

    def test_unrecognized_filename_returns_none(self):
        self.assertIsNone(fss.parse_filename("not_a_sprite.png"))
        self.assertIsNone(fss.parse_filename("Menu_CP_6.png"))   # not zero-padded to 4 digits


class TestShinyParsing(unittest.TestCase):
    """Bulbagarden maintains a SEPARATE "Champions Shiny menu sprites"
    category (359 files - a true 1:1 parallel of the normal-form category),
    with its own naming convention: the shiny suffix is joined with an
    UNDERSCORE and always comes LAST, after any hyphen-joined form suffix
    ("Menu_CP_0003_shiny.png", "Menu_CP_0006-Mega_X_shiny.png") - a
    genuinely different convention from the form suffix itself, not just a
    variant of it. These tests lock in that the shiny suffix is split off
    BEFORE the form is parsed, so it can never bleed into the form field
    (a real risk with a single combined regex, since FILENAME_RE's form
    group is greedy and "Mega_shiny" looks exactly like a plausible form
    name on its own)."""

    def test_base_form_shiny(self):
        self.assertEqual(fss.parse_filename("Menu_CP_0003_shiny.png"), (3, None, True))

    def test_form_plus_shiny_does_not_leak_shiny_into_form(self):
        self.assertEqual(fss.parse_filename("Menu_CP_0003-Mega_shiny.png"), (3, "Mega", True))

    def test_multi_part_form_plus_shiny(self):
        self.assertEqual(fss.parse_filename("Menu_CP_0006-Mega_X_shiny.png"), (6, "Mega_X", True))

    def test_shiny_and_non_shiny_are_distinct_results(self):
        normal = fss.parse_filename("Menu_CP_0059-Hisui.png")
        shiny = fss.parse_filename("Menu_CP_0059-Hisui_shiny.png")
        self.assertEqual(normal, (59, "Hisui", False))
        self.assertEqual(shiny, (59, "Hisui", True))
        self.assertNotEqual(normal, shiny)

    def test_categories_constant_includes_both(self):
        self.assertEqual(len(fss.CATEGORIES), 2)
        self.assertTrue(any("Shiny" in c for c in fss.CATEGORIES))
        self.assertTrue(any("Shiny" not in c for c in fss.CATEGORIES))


class TestChampionsDexMap(unittest.TestCase):

    def test_dex_map_is_keyed_by_int_and_valued_by_str(self):
        self.assertGreater(len(fss.CHAMPIONS_DEX_MAP), 200)
        for k, v in fss.CHAMPIONS_DEX_MAP.items():
            self.assertIsInstance(k, int)
            self.assertIsInstance(v, str)

    def test_known_spot_checks(self):
        self.assertEqual(fss.CHAMPIONS_DEX_MAP[6], "charizard")
        self.assertEqual(fss.CHAMPIONS_DEX_MAP[983], "kingambit")
        self.assertEqual(fss.CHAMPIONS_DEX_MAP[1019], "hydrapple")
        # Added after a live run against the real category found this dex#
        # missing (the in-game roster grew since CHAMPIONS_DEX_MAP was built).
        self.assertEqual(fss.CHAMPIONS_DEX_MAP[923], "pawmot")

    def test_covers_every_m_b_species_except_the_known_provisional_four(self):
        """m-b.json's own "provisional_species" are explicitly flagged there
        as not independently source-confirmed - CHAMPIONS_DEX_MAP (built
        from PokeAPI's own Champions Pokedex) not covering exactly those 4
        is expected and correct, not a bug. If this test starts failing
        because MORE species are missing, that means CHAMPIONS_DEX_MAP
        itself has gone stale against the current regulation file."""
        reg_path = os.path.join(
            os.path.dirname(__file__), "..", "adapters", "pokemon", "regulations", "m-b.json")
        with open(reg_path, encoding="utf-8") as f:
            reg = json.load(f)
        mb_species = set(reg["species"])
        provisional = set(reg.get("provisional_species", []))

        mapped_names = set(fss.CHAMPIONS_DEX_MAP.values())
        # m-b.json spells this "mr. rime"; PokeAPI/CHAMPIONS_DEX_MAP uses "mr. rime" too
        # (kept identical on purpose - see the script's own docstring), so no
        # normalization needed here.
        missing = mb_species - mapped_names
        self.assertEqual(missing, provisional)


if __name__ == "__main__":
    unittest.main()
