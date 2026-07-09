"""
Regression tests for wiring accuracy_addons/ (icon_template_matcher.py,
hp_bar_reader.py, moveset_validator.py, format_rules_validator.py) into the
live pipeline (analyze_matches.py) - see ARCHITECTURE_HANDOFF.md section 2e
for what each tool does and doesn't cover, and why they'd been built as
standalone modules rather than wired in until now.

These tests deliberately do NOT re-validate each addon's own pixel/template
algorithm (hp_bar_reader's HSV column scan, icon_template_matcher's
cv2.matchTemplate) - that was already done, against real footage, when each
module was originally built (see their own docstrings for the exact
per-frame scores). Instead these test analyze_matches.py's NEW wiring logic
around them: does it pick the right event, look up the right validated
region for the right side, and correctly flag (never silently override)
a disagreement - by monkeypatching the addon's own read function to return
a controlled value, isolating "does the wiring do the right thing with
whatever the addon reports" from "is the addon's own pixel math correct."

Run: py -m unittest tests.test_accuracy_addons_wiring -v   (from poc-starter/)
"""

import os
import tempfile
import unittest
from unittest.mock import patch

import analyze_matches as am
import ocr_battle_reader
from accuracy_addons import hp_bar_reader, icon_template_matcher


def _make_dummy_frame_file(path):
    """Content doesn't matter for these tests - hp_fraction_from_bar and
    identify_status_icon are monkeypatched to return controlled values, so
    this just needs to be a real, cv2-openable file so the "frame missing/
    unreadable" skip path isn't accidentally triggered instead."""
    from PIL import Image
    Image.new("RGB", (64, 64), color=(10, 10, 10)).save(path)


class TestCrossCheckHpBarEvents(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.frame_path = os.path.join(self.tmp.name, "b_00001.jpg")
        _make_dummy_frame_file(self.frame_path)

    def _event(self, **overrides):
        e = {"event": "hp_change", "actor": "opponent", "hp_percent": 80.0,
             "reference_frame": self.frame_path, "confidence": 1.0}
        e.update(overrides)
        return e

    def test_non_hp_change_event_is_untouched(self):
        e = {"event": "move_used", "actor": "opponent", "reference_frame": self.frame_path}
        events = [dict(e)]
        am.cross_check_hp_bar_events(events)
        self.assertEqual(events[0], e)

    def test_missing_reference_frame_is_skipped(self):
        e = self._event(reference_frame=None)
        events = [e]
        am.cross_check_hp_bar_events(events)
        self.assertNotIn("[HP pixel-check", e.get("detail", ""))

    def test_unvalidated_actor_is_skipped(self):
        e = self._event(actor="both")
        events = [e]
        am.cross_check_hp_bar_events(events)
        self.assertNotIn("[HP pixel-check", e.get("detail", ""))

    def test_non_numeric_hp_percent_is_skipped(self):
        e = self._event(hp_percent="unknown")
        events = [e]
        am.cross_check_hp_bar_events(events)
        self.assertNotIn("[HP pixel-check", e.get("detail", ""))

    def test_agreement_leaves_event_untouched(self):
        e = self._event(hp_percent=80.0, confidence=1.0)
        events = [e]
        with patch.object(hp_bar_reader, "hp_fraction_from_bar", return_value=0.81):
            am.cross_check_hp_bar_events(events)
        self.assertEqual(e["confidence"], 1.0)
        self.assertNotIn("[HP pixel-check", e.get("detail", ""))

    def test_disagreement_lowers_confidence_and_flags_detail(self):
        e = self._event(hp_percent=90.0, confidence=1.0, detail="Incineroar took damage")
        events = [e]
        with patch.object(hp_bar_reader, "hp_fraction_from_bar", return_value=0.20):
            am.cross_check_hp_bar_events(events)
        self.assertLessEqual(e["confidence"], 0.5)
        self.assertIn("[HP pixel-check", e["detail"])
        self.assertIn("Incineroar took damage", e["detail"])   # original detail preserved

    def test_unreadable_frame_is_skipped_not_raised(self):
        bad_path = os.path.join(self.tmp.name, "not_an_image.jpg")
        with open(bad_path, "w") as f:
            f.write("not a real jpeg")
        e = self._event(reference_frame=bad_path)
        events = [e]
        am.cross_check_hp_bar_events(events)   # must not raise
        self.assertNotIn("[HP pixel-check", e.get("detail", ""))

    def test_player_side_uses_player_region(self):
        e = self._event(actor="player", hp_percent=50.0)
        events = [e]
        with patch.object(hp_bar_reader, "hp_fraction_from_bar", return_value=0.05) as mock_read:
            am.cross_check_hp_bar_events(events)
        used_region = mock_read.call_args.kwargs.get("region") or mock_read.call_args.args[-1]
        self.assertEqual(used_region, hp_bar_reader.PLAYER_BOTTOM_LEFT_HP_BAR)

    def test_empty_list_is_safe(self):
        self.assertEqual(am.cross_check_hp_bar_events([]), [])


class TestCrossCheckStatusEvents(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.frame_path = os.path.join(self.tmp.name, "b_00002.jpg")
        _make_dummy_frame_file(self.frame_path)

    def _event(self, **overrides):
        e = {"event": "status_inflicted", "actor": "opponent", "status": "Burn",
             "reference_frame": self.frame_path, "confidence": 1.0}
        e.update(overrides)
        return e

    def test_non_status_event_is_untouched(self):
        e = {"event": "move_used", "actor": "opponent", "status": "Burn",
             "reference_frame": self.frame_path}
        events = [dict(e)]
        am.cross_check_status_events(events)
        self.assertEqual(events[0], e)

    def test_player_side_is_left_unchecked(self):
        """icon_template_matcher's burn badge was only validated on the
        OPPONENT plate - a player-side burn claim must not be touched."""
        e = self._event(actor="player")
        events = [e]
        with patch.object(icon_template_matcher, "identify_status_icon", return_value=None):
            am.cross_check_status_events(events)
        self.assertNotIn("[status pixel-check", e.get("detail", ""))

    def test_non_burn_status_is_ignored(self):
        e = self._event(status="Paralysis")
        events = [e]
        with patch.object(icon_template_matcher, "identify_status_icon", return_value=None):
            am.cross_check_status_events(events)
        self.assertNotIn("[status pixel-check", e.get("detail", ""))

    def test_confirmed_burn_leaves_event_untouched(self):
        e = self._event(confidence=1.0)
        events = [e]
        with patch.object(icon_template_matcher, "identify_status_icon", return_value="burn"):
            am.cross_check_status_events(events)
        self.assertEqual(e["confidence"], 1.0)
        self.assertNotIn("[status pixel-check", e.get("detail", ""))

    def test_unconfirmed_burn_flags_disagreement(self):
        e = self._event(confidence=1.0, detail="Floette was burned.")
        events = [e]
        with patch.object(icon_template_matcher, "identify_status_icon", return_value=None):
            am.cross_check_status_events(events)
        self.assertLessEqual(e["confidence"], 0.5)
        self.assertIn("[status pixel-check", e["detail"])
        self.assertIn("Floette was burned.", e["detail"])

    def test_missing_reference_frame_is_skipped(self):
        e = self._event(reference_frame=None)
        events = [e]
        am.cross_check_status_events(events)
        self.assertNotIn("[status pixel-check", e.get("detail", ""))

    def test_empty_list_is_safe(self):
        self.assertEqual(am.cross_check_status_events([]), [])


class TestCrossCheckReferenceFrameVisibility(unittest.TestCase):
    """cross_check_reference_frame_visibility - the dynamic-camera fix: a
    reference photo is picked by nearest TIMESTAMP alone (attach_reference_
    frames), with no guarantee Pokemon Champions' moving camera was actually
    pointed at the relevant side at that instant. This checks the WIRING
    (does it call species_readable_in_frame with the right candidates, flag
    the right way on a False result) - species_readable_in_frame's own OCR
    logic is tested separately in test_ocr_battle_reader.py."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.frame_path = os.path.join(self.tmp.name, "b_00003.jpg")
        _make_dummy_frame_file(self.frame_path)

    def _event(self, **overrides):
        e = {"event": "move_used", "actor": "opponent", "pokemon": "Rillaboom",
             "reference_frame": self.frame_path, "confidence": 1.0}
        e.update(overrides)
        return e

    def test_visible_leaves_event_untouched(self):
        e = self._event()
        events = [e]
        with patch.object(ocr_battle_reader, "species_readable_in_frame", return_value=True):
            am.cross_check_reference_frame_visibility(events)
        self.assertTrue(e["reference_frame_shows_subject"])
        self.assertEqual(e["confidence"], 1.0)
        self.assertNotIn("[reference-frame check", e.get("detail", ""))

    def test_not_visible_lowers_confidence_and_flags_detail(self):
        e = self._event(confidence=1.0, detail="Rillaboom used Grassy Glide")
        events = [e]
        with patch.object(ocr_battle_reader, "species_readable_in_frame", return_value=False):
            am.cross_check_reference_frame_visibility(events)
        self.assertFalse(e["reference_frame_shows_subject"])
        self.assertLessEqual(e["confidence"], 0.5)
        self.assertIn("[reference-frame check", e["detail"])
        self.assertIn("Rillaboom used Grassy Glide", e["detail"])   # original detail preserved

    def test_passes_pokemon_and_roster_conflict_species_as_candidates(self):
        e = self._event(roster_conflict_species=["Kingambit"])
        events = [e]
        with patch.object(ocr_battle_reader, "species_readable_in_frame", return_value=True) as mock_read:
            am.cross_check_reference_frame_visibility(events)
        candidates = mock_read.call_args.args[1]
        self.assertEqual(candidates, ["Rillaboom", "Kingambit"])

    def test_event_missing_pokemon_is_skipped(self):
        e = {"event": "field_state", "actor": "both", "reference_frame": self.frame_path}
        events = [dict(e)]
        am.cross_check_reference_frame_visibility(events)
        self.assertEqual(events[0], e)

    def test_unknown_actor_is_skipped(self):
        e = self._event(actor="both")
        events = [e]
        am.cross_check_reference_frame_visibility(events)
        self.assertNotIn("reference_frame_shows_subject", e)

    def test_missing_reference_frame_is_skipped(self):
        e = self._event(reference_frame=None)
        events = [e]
        am.cross_check_reference_frame_visibility(events)
        self.assertNotIn("reference_frame_shows_subject", e)

    def test_unreadable_frame_is_skipped_not_raised(self):
        bad_path = os.path.join(self.tmp.name, "not_an_image.jpg")
        with open(bad_path, "w") as f:
            f.write("not a real jpeg")
        e = self._event(reference_frame=bad_path)
        events = [e]
        am.cross_check_reference_frame_visibility(events)   # must not raise
        self.assertNotIn("reference_frame_shows_subject", e)

    def test_empty_list_is_safe(self):
        self.assertEqual(am.cross_check_reference_frame_visibility([]), [])


class TestMovesetValidatorIsWired(unittest.TestCase):
    """flag_implausible_moves itself is accuracy_addons/moveset_validator.py's
    own, already-real function - these just confirm analyze_matches.py
    actually imports and can call it (the wiring), not the check logic
    itself, which is that module's own responsibility."""

    def test_moveset_validator_importable_from_analyze_matches(self):
        self.assertTrue(hasattr(am, "moveset_validator"))

    def test_flag_implausible_moves_callable_and_safe_on_empty(self):
        self.assertEqual(am.moveset_validator.flag_implausible_moves([]), [])


class TestRegulationStalenessCheck(unittest.TestCase):

    def test_no_mismatch_prints_nothing(self):
        import io
        from contextlib import redirect_stdout
        adapter_rules = {"active_per_side": 2, "regulation": "m-b"}
        regulation_rules = {"banned_species_categories": ["mythical", "restricted_legendary"],
                             "legal_mechanics": {"terastallization": False},
                             "regulation": "m-b"}
        buf = io.StringIO()
        with redirect_stdout(buf):
            am.check_regulation_staleness(adapter_rules, regulation_rules)
        self.assertNotIn("mismatch", buf.getvalue().lower())

    def test_real_mismatch_is_printed(self):
        import io
        from contextlib import redirect_stdout
        adapter_rules = {"active_per_side": 1, "regulation": "m-b"}   # wrong: claims singles
        regulation_rules = {"banned_species_categories": ["mythical", "restricted_legendary"],
                             "legal_mechanics": {"terastallization": False},
                             "regulation": "m-b"}
        buf = io.StringIO()
        with redirect_stdout(buf):
            am.check_regulation_staleness(adapter_rules, regulation_rules)
        self.assertIn("doubles_format", buf.getvalue())

    def test_missing_showdown_data_does_not_raise(self):
        from accuracy_addons import format_rules_validator
        with patch.object(format_rules_validator, "load_showdown_data", return_value=None):
            am.check_regulation_staleness({"active_per_side": 2}, {})   # must not raise


class TestUseAccuracyAddonsFlagExists(unittest.TestCase):

    def test_help_text_mentions_the_new_flag(self):
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "analyze_matches.py", "--help"],
            capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.assertIn("--use-accuracy-addons", result.stdout)


if __name__ == "__main__":
    unittest.main()
