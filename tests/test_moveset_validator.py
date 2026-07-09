"""
Tests for accuracy_addons/moveset_validator.py - specifically the
full-dex auto-detection logic added when wiring in "option 2" (Showdown
learnset export support, see ARCHITECTURE_HANDOFF.md). This does NOT
re-test whether Showdown's learnset data is itself correct (that's an
external data source) - it tests that this module correctly prefers a
full-dex export file the moment one exists on disk, and falls back to
the bundled 15-species starter file otherwise, plus the pre-existing
is_plausible_move/flag_implausible_moves behavior.

Run: py -m unittest tests.test_moveset_validator -v   (from poc-starter/)
"""

import json
import os
import tempfile
import unittest

from accuracy_addons import moveset_validator as mv


class TestResolveDefaultDataPath(unittest.TestCase):
    """_resolve_default_data_path() is the "TRULY zero code changes" switch:
    once tools/export_showdown_learnsets.js has been run on the user's own
    machine and its output dropped at data/showdown_learnsets_full.json,
    every subsequent import of this module should pick it up automatically
    with no code edit required."""

    def test_falls_back_to_starter_when_full_file_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            full = os.path.join(tmp, "showdown_learnsets_full.json")
            starter = os.path.join(tmp, "showdown_learnsets_starter.json")
            self.assertFalse(os.path.exists(full))
            result = mv._resolve_default_data_path(full, starter)
            self.assertEqual(result, starter)

    def test_prefers_full_file_the_moment_it_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            full = os.path.join(tmp, "showdown_learnsets_full.json")
            starter = os.path.join(tmp, "showdown_learnsets_starter.json")
            with open(full, "w", encoding="utf-8") as f:
                f.write("{}")
            result = mv._resolve_default_data_path(full, starter)
            self.assertEqual(result, full)

    def test_module_level_default_data_path_ends_with_a_known_data_filename(self):
        """DEFAULT_DATA_PATH is resolved once at import time from whichever
        of the two files actually exists on disk (see
        test_falls_back_to_starter_when_full_file_absent /
        test_prefers_full_file_the_moment_it_exists above for the isolated,
        environment-independent version of this logic) - it should always
        be ONE of the two known filenames, never anything else. Doesn't
        assert which one, since that legitimately depends on whether the
        user has run tools/export_showdown_learnsets.js yet in this
        environment."""
        self.assertTrue(
            mv.DEFAULT_DATA_PATH.endswith("showdown_learnsets_full.json")
            or mv.DEFAULT_DATA_PATH.endswith("showdown_learnsets_starter.json")
        )


class TestIsPlausibleMove(unittest.TestCase):

    def test_known_species_known_move_is_true(self):
        self.assertTrue(mv.is_plausible_move("Charizard", "Flamethrower"))

    def test_known_species_impossible_move_is_false(self):
        # Bulbasaur (in the 15-species starter set) has never learned Hydro Pump.
        self.assertFalse(mv.is_plausible_move("Bulbasaur", "Hydro Pump"))

    def test_unknown_species_returns_none_not_false(self):
        # Hydreigon is real VGC-relevant but NOT in the 15-species starter data -
        # must return None ("can't check"), never a false positive/negative.
        # Pinned to the starter path explicitly (not DEFAULT_DATA_PATH) since
        # a real full-dex export may legitimately exist on disk in this
        # environment now (see TestResolveDefaultDataPath) - once it does,
        # Hydreigon becomes genuinely checkable and this premise no longer
        # holds against the default path.
        self.assertIsNone(mv.is_plausible_move("Hydreigon", "Dark Pulse", path=mv._STARTER_DATA_PATH))

    def test_hydreigon_is_checkable_against_the_full_dex_export(self):
        """Companion to the test above: once the real full-dex export exists
        (confirmed present in this environment - a genuine 818-species file
        the user generated via tools/export_showdown_learnsets.js), Hydreigon
        + Dark Pulse should resolve to a real, confident True - this is the
        actual payoff of wiring in "option 2." Skipped if that file hasn't
        been generated yet in whatever environment runs this test."""
        if not os.path.exists(mv._FULL_DATA_PATH):
            self.skipTest("full-dex export not present in this environment yet")
        self.assertTrue(mv.is_plausible_move("Hydreigon", "Dark Pulse", path=mv._FULL_DATA_PATH))

    def test_missing_species_or_move_returns_none(self):
        self.assertIsNone(mv.is_plausible_move(None, "Flamethrower"))
        self.assertIsNone(mv.is_plausible_move("Charizard", None))

    def test_case_and_formatting_insensitive(self):
        self.assertEqual(
            mv.is_plausible_move("charizard", "flamethrower"),
            mv.is_plausible_move("CHARIZARD", "Fire Blast".replace("Fire Blast", "Flamethrower")),
        )


class TestMoveName(unittest.TestCase):
    """_move_name() - the fallback fix for a real gap found while building
    decision_windows.py: no code path in this project actually populates a
    structured `move` field on a real event, so the OLD move-field-only
    lookup never matched anything on real jobs. See the function's own
    docstring for the full writeup."""

    def test_prefers_structured_move_field_when_present(self):
        e = {"event": "move_used", "pokemon": "Charizard", "move": "Flamethrower", "detail": "used a move!"}
        self.assertEqual(mv._move_name(e), "Flamethrower")

    def test_falls_back_to_detail_when_no_move_field(self):
        e = {"event": "move_used", "pokemon": "Charizard", "detail": "Flamethrower"}
        self.assertEqual(mv._move_name(e), "Flamethrower")

    def test_strips_failed_suffix(self):
        e = {"event": "move_used", "pokemon": "Charizard", "detail": "Flamethrower (failed)"}
        self.assertEqual(mv._move_name(e), "Flamethrower")

    def test_strips_a_trailing_bracketed_annotation_from_another_check(self):
        e = {"event": "move_used", "pokemon": "Charizard",
             "detail": "Flamethrower [reference-frame check: subject not visible]"}
        self.assertEqual(mv._move_name(e), "Flamethrower")

    def test_strips_multiple_trailing_bracketed_annotations(self):
        e = {"event": "move_used", "pokemon": "Charizard",
             "detail": "Flamethrower [reference-frame check: x] [move-legality check: y]"}
        self.assertEqual(mv._move_name(e), "Flamethrower")

    def test_no_move_and_empty_detail_returns_none(self):
        self.assertIsNone(mv._move_name({"event": "move_used", "pokemon": "Charizard"}))
        self.assertIsNone(mv._move_name({"event": "move_used", "pokemon": "Charizard", "detail": ""}))

    # --- 2026-07-05 additions: real battle-log sentence shapes found while
    # cross-checking the new full-dex export against every move_used event
    # in jobs/ (task #131) - see _move_name's own docstring "SECOND ROUND"
    # section for the full writeup of why these matter (roughly half of
    # what looked like real move-legality flags were actually this parsing
    # gap, not a real implausible move).

    def test_strips_species_used_prefix(self):
        e = {"event": "move_used", "pokemon": "Hydreigon", "detail": "Hydreigon used Draco Meteor"}
        self.assertEqual(mv._move_name(e), "Draco Meteor")

    def test_strips_the_opposing_species_used_prefix_and_trailing_bang(self):
        e = {"event": "move_used", "pokemon": "Primarina",
             "detail": "The opposing Primarina used Sparkling Aria!"}
        self.assertEqual(mv._move_name(e), "Sparkling Aria")

    def test_used_prefix_is_anchored_to_this_events_own_pokemon_field(self):
        # A different Pokemon's name appearing in the sentence must NOT be
        # stripped as if it were a prefix - only e["pokemon"] itself is.
        e = {"event": "move_used", "pokemon": "Rotom", "detail": "Rotom used Discharge"}
        self.assertEqual(mv._move_name(e), "Discharge")

    def test_strips_hit_clause_with_effectiveness_note(self):
        e = {"event": "move_used", "pokemon": "Garchomp", "detail": "Muddy Water hit Garchomp (Effective)"}
        self.assertEqual(mv._move_name(e), "Muddy Water")

    def test_strips_missed_clause(self):
        e = {"event": "move_used", "pokemon": "Charizard",
             "detail": "Heat Wave missed opponent's Incineroar"}
        self.assertEqual(mv._move_name(e), "Heat Wave")

    def test_strips_bare_failed_suffix_without_parens(self):
        e = {"event": "move_used", "pokemon": "Gallade", "detail": "Sacred Sword failed"}
        self.assertEqual(mv._move_name(e), "Sacred Sword")

    def test_strips_failed_due_to_reason_parenthetical(self):
        e = {"event": "move_used", "pokemon": "Sinistcha",
             "detail": "Strength Sap (failed due to Taunt)"}
        self.assertEqual(mv._move_name(e), "Strength Sap")

    def test_combined_prefix_and_bang_and_bracket(self):
        # Realistic worst case: sentence wrapper + bracket annotation both present.
        e = {"event": "move_used", "pokemon": "Hydreigon",
             "detail": "The opposing Hydreigon used Draco Meteor! [reference-frame check: ok]"}
        self.assertEqual(mv._move_name(e), "Draco Meteor")

    # --- 2026-07-05 additions (task #139): found by actually re-running
    # flag_implausible_moves() against every real jobs/*/events.json on disk
    # as an end-to-end accuracy test of everything task #131/#138 shipped -
    # roughly a dozen real events across real jobs hit these three gaps and
    # were wrongly flagged as "implausible" moves that are perfectly legal.

    def test_strips_bare_used_prefix_with_no_species_repeated(self):
        # Real shape found in jobs/3e46bb33364c: the sentence doesn't always
        # restate the species (it's already on the event's own `pokemon`
        # field) - "used Sparkling Aria", not "Primarina used Sparkling Aria".
        e = {"event": "move_used", "pokemon": "Primarina", "detail": "used Sparkling Aria"}
        self.assertEqual(mv._move_name(e), "Sparkling Aria")

    def test_bare_used_prefix_does_not_swallow_a_different_species_sentence(self):
        # The bare "used " strip only fires when "used" is the very FIRST
        # word - a sentence naming a DIFFERENT Pokemon (a real
        # species-misattribution case this checker should keep catching, see
        # jobs/d7255d9ecc40's real Porygon2/Hydreigon mismatch) starts with
        # "The opposing ...", not "used ", so it's correctly left untouched.
        e = {"event": "move_used", "pokemon": "Porygon2",
             "detail": "The opposing Hydreigon used Draco Meteor!"}
        self.assertEqual(mv._move_name(e), "The opposing Hydreigon used Draco Meteor")

    def test_strips_on_target_clause_with_parenthetical_and_trailing_period(self):
        # Real shape found in jobs/3e46bb33364c: "<move> on <target>
        # (<annotation>)." - the parenthetical here is NOT a failure reason,
        # just an unrelated on-screen note, and the whole thing ends in a
        # period rather than "!" or nothing.
        e = {"event": "move_used", "pokemon": "Rotom",
             "detail": "Rotom used Will-O-Wisp on Weavile (Scrafty on screen)."}
        self.assertEqual(mv._move_name(e), "Will-O-Wisp")

    def test_strips_on_target_clause_second_real_example(self):
        e = {"event": "move_used", "pokemon": "Rotom",
             "detail": "Rotom used Hydro Pump on Arcanine (Hydreigon on screen)."}
        self.assertEqual(mv._move_name(e), "Hydro Pump")

    def test_vague_type_only_description_returns_none_not_a_fake_move_name(self):
        # Real shape found in jobs/3e46bb33364c: a vision read that could
        # only identify the move's TYPE, not its actual name. Treating "a
        # Dark-type move" as if it were a literal move name produces a
        # nonsense flag on every occurrence - worse than useless, since a
        # human reviewer can't act on "'a Dark-type move' isn't in
        # Meowscarada's learnset" the way they could act on a real move name.
        e = {"event": "move_used", "pokemon": "Meowscarada",
             "detail": "used a Dark-type move on Primarina"}
        self.assertIsNone(mv._move_name(e))

    def test_vague_type_only_description_without_a_target_clause(self):
        e = {"event": "move_used", "pokemon": "Meowscarada",
             "detail": "Meowscarada used a Grass-type move"}
        self.assertIsNone(mv._move_name(e))


class TestFlagImplausibleMoves(unittest.TestCase):

    def test_implausible_move_lowers_confidence_and_flags_detail(self):
        events = [{"event": "move_used", "pokemon": "Bulbasaur", "move": "Hydro Pump",
                   "confidence": 1.0, "detail": "Bulbasaur used Hydro Pump"}]
        mv.flag_implausible_moves(events)
        self.assertLessEqual(events[0]["confidence"], 0.3)
        self.assertIn("move-legality check", events[0]["detail"])
        self.assertIn("Bulbasaur used Hydro Pump", events[0]["detail"])  # original preserved

    def test_plausible_move_is_untouched(self):
        e = {"event": "move_used", "pokemon": "Charizard", "move": "Flamethrower", "confidence": 1.0}
        events = [dict(e)]
        mv.flag_implausible_moves(events)
        self.assertEqual(events[0], e)

    def test_unknown_species_is_untouched(self):
        # Pinned to the starter path - see the matching note in
        # TestIsPlausibleMove.test_unknown_species_returns_none_not_false.
        e = {"event": "move_used", "pokemon": "Hydreigon", "move": "Dark Pulse", "confidence": 1.0}
        events = [dict(e)]
        mv.flag_implausible_moves(events, path=mv._STARTER_DATA_PATH)
        self.assertEqual(events[0], e)

    def test_flags_using_detail_when_no_move_field_present(self):
        """The real-world case: a real event today has NO `move` field at
        all (see TestMoveName's docstring) - detail is what actually needs
        to drive this check."""
        events = [{"event": "move_used", "pokemon": "Bulbasaur", "confidence": 1.0,
                   "detail": "Hydro Pump"}]
        mv.flag_implausible_moves(events)
        self.assertLessEqual(events[0]["confidence"], 0.3)
        self.assertIn("move-legality check", events[0]["detail"])

    def test_non_move_used_event_is_untouched(self):
        e = {"event": "hp_change", "pokemon": "Bulbasaur", "move": "Hydro Pump"}
        events = [dict(e)]
        mv.flag_implausible_moves(events)
        self.assertEqual(events[0], e)

    def test_empty_list_is_safe(self):
        self.assertEqual(mv.flag_implausible_moves([]), [])

    def test_mutates_and_returns_same_list(self):
        events = [{"event": "move_used", "pokemon": "Bulbasaur", "move": "Hydro Pump", "confidence": 1.0}]
        result = mv.flag_implausible_moves(events)
        self.assertIs(result, events)


class TestLoadLearnsets(unittest.TestCase):

    def test_missing_file_returns_empty_dict_not_error(self):
        result = mv.load_learnsets(path="/tmp/definitely_missing_learnsets_file.json")
        self.assertEqual(result, {})

    def test_loaded_data_is_cached_by_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "custom_learnsets.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"testmon": ["testmove"]}, f)
            first = mv.load_learnsets(path=path)
            # Mutate the file on disk after first load - cache should still
            # return the original in-memory data, not re-read.
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"testmon": ["differentmove"]}, f)
            second = mv.load_learnsets(path=path)
            self.assertEqual(first, second)


class TestReadJsonRobustEncoding(unittest.TestCase):
    """Regression tests for the exact real-world failure a user hit: running
    `node export_showdown_learnsets.js > ../data/showdown_learnsets_full.json`
    in Windows PowerShell writes the file as UTF-16LE with a BOM (not UTF-8,
    even though node itself printed plain UTF-8 text) - a plain
    `open(path, encoding="utf-8")` raised
    `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 0`
    on a real file generated this exact way."""

    def _write_and_read(self, tmp, encoding, add_bom=False):
        path = os.path.join(tmp, "learnsets.json")
        payload = json.dumps({"hydreigon": ["darkpulse", "dracometeor"]})
        with open(path, "wb") as f:
            if add_bom and encoding == "utf-16-le":
                f.write(b"\xff\xfe")
                f.write(payload.encode("utf-16-le"))
            elif add_bom and encoding == "utf-16-be":
                f.write(b"\xfe\xff")
                f.write(payload.encode("utf-16-be"))
            elif add_bom and encoding == "utf-8":
                f.write(b"\xef\xbb\xbf")
                f.write(payload.encode("utf-8"))
            else:
                f.write(payload.encode(encoding))
        return mv._read_json_robust_encoding(path)

    def test_plain_utf8_no_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._write_and_read(tmp, "utf-8")
            self.assertEqual(result, {"hydreigon": ["darkpulse", "dracometeor"]})

    def test_utf8_with_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._write_and_read(tmp, "utf-8", add_bom=True)
            self.assertEqual(result, {"hydreigon": ["darkpulse", "dracometeor"]})

    def test_utf16_le_with_bom_matches_powershell_redirection_output(self):
        """This is the exact real failure mode: PowerShell's `>` redirect."""
        with tempfile.TemporaryDirectory() as tmp:
            result = self._write_and_read(tmp, "utf-16-le", add_bom=True)
            self.assertEqual(result, {"hydreigon": ["darkpulse", "dracometeor"]})

    def test_utf16_be_with_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._write_and_read(tmp, "utf-16-be", add_bom=True)
            self.assertEqual(result, {"hydreigon": ["darkpulse", "dracometeor"]})

    def test_load_learnsets_end_to_end_with_utf16_bom_file(self):
        """The full load_learnsets() path (not just the low-level decode
        helper) must also succeed against a UTF-16LE-BOM file, since that's
        what actually broke for the user."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "learnsets_utf16.json")
            payload = json.dumps({"hydreigon": ["darkpulse"]})
            with open(path, "wb") as f:
                f.write(b"\xff\xfe")
                f.write(payload.encode("utf-16-le"))
            data = mv.load_learnsets(path=path)
            self.assertIn("hydreigon", data)
            self.assertIn("darkpulse", data["hydreigon"])
            # and is_plausible_move works end-to-end through the same path
            self.assertTrue(mv.is_plausible_move("Hydreigon", "Dark Pulse", path=path))


class TestAltFormeLearnsetInheritance(unittest.TestCase):
    """Real bug found + fixed 2026-07-05 while validating the full-dex
    export against real footage (task #131): accuracy_addons/tools/
    export_showdown_learnsets.js originally exported an alternate forme's
    OWN (deliberately sparse) learnsets.ts entry only - e.g. Rotom-Wash had
    just "Hydro Pump," not the 67 moves base Rotom can learn - since
    Showdown stores a forme's real move pool as its base species' learnset
    PLUS its own forme-exclusive move(s), not a fully separate list. Fixed
    by merging in the base species' learnset at export time (see the
    script's own comment for the full writeup, including which real species
    were affected: every Rotom appliance forme, both Necrozma fusion
    formes, both Crowned formes). These tests run against the REAL,
    regenerated data/showdown_learnsets_full.json (skipped if that file
    isn't present in this environment), not a synthetic fixture, since the
    whole point is confirming the actual shipped data has the fix."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(mv._FULL_DATA_PATH):
            raise unittest.SkipTest("full-dex export not present in this environment yet")

    def test_rotom_wash_inherits_base_rotoms_moves(self):
        # Thunderbolt is a real, common Rotom-Wash VGC move (base Rotom's
        # own learnset), NOT a Rotom-Wash-exclusive move - only checkable
        # at all once the base-species merge is in place.
        self.assertTrue(mv.is_plausible_move("Rotom-Wash", "Thunderbolt", path=mv._FULL_DATA_PATH))

    def test_rotom_wash_keeps_its_own_forme_exclusive_move(self):
        # The merge must be additive (union), not a replacement that drops
        # the forme's own signature move.
        self.assertTrue(mv.is_plausible_move("Rotom-Wash", "Hydro Pump", path=mv._FULL_DATA_PATH))

    def test_rotom_wash_still_correctly_rejects_a_real_non_move(self):
        # Sanity check the merge didn't accidentally make everything True -
        # Roost is a real move neither Rotom nor any of its formes learn.
        self.assertFalse(mv.is_plausible_move("Rotom-Wash", "Roost", path=mv._FULL_DATA_PATH))

    def test_necrozma_dusk_mane_inherits_base_necrozmas_moves(self):
        self.assertTrue(mv.is_plausible_move("Necrozma-Dusk-Mane", "Photon Geyser", path=mv._FULL_DATA_PATH))

    def test_zacian_crowned_inherits_base_zacians_moves(self):
        self.assertTrue(mv.is_plausible_move("Zacian-Crowned", "Play Rough", path=mv._FULL_DATA_PATH))


class TestChampionsFormatSpecificOverrides(unittest.TestCase):
    """A user directly asked "does the system know what moves are legal in
    what FORMATS, not just what generation" - the honest answer up to this
    point was no (is_plausible_move is a lenient "ever learnable in gen 9,
    any regulation" check by design). This closes that gap for a real
    subset of species: Pokemon Showdown has its own dedicated `champions`
    mod (data/mods/champions/learnsets.ts on the live smogon/pokemon-showdown
    GitHub repo, confirmed present 2026-07-05) with a genuinely DIFFERENT,
    narrower movepool for 48 species than vanilla gen 9 allows - e.g. real
    Champions-Charizard has 72 learnable moves vs. vanilla gen 9's 129,
    missing Dynamic Punch/False Swipe/Hidden Power/etc. while separately
    gaining Ancient Power/Bite/Dragon Rush. These tests run against the
    REAL, directly-fetched override file (skipped if it isn't present in
    this environment), not a synthetic fixture - see
    accuracy_addons/tools/fetch_champions_learnset_overrides.py for exactly
    how it was produced and how to refresh it."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(mv._CHAMPIONS_OVERRIDES_PATH):
            raise unittest.SkipTest("champions learnset overrides not present in this environment yet")
        if not os.path.exists(mv._FULL_DATA_PATH):
            raise unittest.SkipTest("full-dex export not present in this environment yet")

    def test_charizard_rejects_a_real_gen9_move_champions_actually_cut(self):
        self.assertFalse(mv.is_plausible_move("Charizard", "Dynamic Punch"))

    def test_charizard_accepts_a_champions_only_addition(self):
        self.assertTrue(mv.is_plausible_move("Charizard", "Ancient Power"))

    def test_charizard_still_accepts_a_move_legal_in_both(self):
        self.assertTrue(mv.is_plausible_move("Charizard", "Flamethrower"))

    def test_slowking_galar_is_tightly_curated_in_champions(self):
        self.assertFalse(mv.is_plausible_move("Slowking-Galar", "Acid"))
        self.assertTrue(mv.is_plausible_move("Slowking-Galar", "Belch"))

    def test_non_override_species_still_uses_the_lenient_generation_check(self):
        self.assertTrue(mv.is_plausible_move("Hydreigon", "Dark Pulse"))

    def test_override_does_not_apply_to_the_starter_data_path(self):
        """load_learnsets() only merges Champions overrides in for the real
        _FULL_DATA_PATH, deliberately not for the starter file or any other
        caller-supplied path. The starter file's own charizard entry
        (transcribed from vanilla Showdown data, real, independent of this
        override) already includes "Dynamic Punch" - the exact move the
        champions override removes - so this is a real discriminating check,
        not a tautology."""
        self.assertTrue(mv.is_plausible_move("Charizard", "Dynamic Punch", path=mv._STARTER_DATA_PATH))
        self.assertFalse(mv.is_plausible_move("Charizard", "Dynamic Punch"))   # default path: override applied
        self.assertFalse(mv.is_plausible_move("Charizard", "Ancient Power", path=mv._STARTER_DATA_PATH))
        self.assertTrue(mv.is_plausible_move("Charizard", "Ancient Power"))


if __name__ == "__main__":
    unittest.main()
