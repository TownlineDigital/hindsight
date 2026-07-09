"""
Tests for ocr_battle_reader.py - the local, free, deterministic OCR reader
that replaces a Gemini vision call for the parts of a Pokemon battle frame
that are just exact on-screen text (see the module's own docstring and
ARCHITECTURE_HANDOFF.md's OCR write-up for the full reasoning).

These use SYNTHETIC frames (rendered with PIL, known ground-truth text)
rather than real captured video frames - real footage is a specific
streamer's personal content (webcam, chat overlay, channel branding) and
isn't appropriate to commit as a permanent test fixture. The preprocessing
recipe itself (HSV isolation -> invert -> pad) WAS validated against real
captured frames during development (see ocr_battle_reader.py's docstring
and ARCHITECTURE_HANDOFF.md) - these tests instead confirm the module's
actual code behaves correctly and stays correct, using text this project
controls completely. Treat this the same as the project's existing "two
tiers of testing" split (tests/README.md): this covers the deterministic
code path; genuinely judging real-footage OCR quality is the same kind of
human-in-the-loop job grade_matches.py already exists for.

Requires tesseract + a DejaVu font to be installed (both already required
by requirements.txt / present in this project's dev environment) - skips
cleanly rather than failing if either is missing somewhere else.

Run: py -m unittest tests.test_ocr_battle_reader -v   (from poc-starter/)
"""

import os
import sys
import unittest

import numpy as np
import cv2

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import ocr_battle_reader as ocr  # noqa: E402

try:
    import pytesseract
    pytesseract.get_tesseract_version()
    _TESSERACT_OK = True
except Exception:
    _TESSERACT_OK = False

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
_FONT_PATH = next((p for p in _FONT_CANDIDATES if os.path.exists(p)), None)


def _make_banner_frame(text, size=(800, 450)):
    """A synthetic frame with `text` rendered white-on-dark inside
    ocr_battle_reader.BOTTOM_BANNER_REGION, mimicking the real banner's
    look (light text over a dark background) without depending on any
    real captured footage."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", size, (20, 20, 25))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(_FONT_PATH, 22)
    top_frac, _, _, _ = ocr.BOTTOM_BANNER_REGION
    y = int(size[1] * top_frac) + 4
    draw.text((30, y), text, fill=(255, 255, 255), font=font)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def _make_plate_frame(name, hp_text, size=(800, 450)):
    """A synthetic frame with a name line and an HP line rendered inside
    ocr_battle_reader.NAME_PLATE_VALIDATED, on a colored (not plain black)
    background - real name plates are colored/textured, not flat, so this
    at least exercises the same HSV-isolation step against non-black
    surroundings rather than the easiest possible case."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", size, (40, 40, 90))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(_FONT_PATH, 20)
    top_frac, _, _, _ = ocr.NAME_PLATE_VALIDATED
    y0 = int(size[1] * top_frac)
    draw.text((10, y0 + 5), name, fill=(255, 255, 255), font=font)
    draw.text((10, y0 + 35), hp_text, fill=(255, 255, 255), font=font)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


@unittest.skipUnless(_TESSERACT_OK and _FONT_PATH, "tesseract or a test font isn't available here")
class TestReadBottomBanner(unittest.TestCase):
    def test_reads_a_move_used_line(self):
        frame = _make_banner_frame("Greninja used Hydro Pump!")
        self.assertEqual(ocr.read_bottom_banner(frame), "Greninja used Hydro Pump!")

    def test_reads_an_effectiveness_line(self):
        frame = _make_banner_frame("It's super effective!")
        self.assertEqual(ocr.read_bottom_banner(frame), "It's super effective!")

    def test_reads_an_opponent_fainting_line(self):
        """The exact category of line the real Staraptor/Charizard bug's
        frame showed - see ARCHITECTURE_HANDOFF.md."""
        frame = _make_banner_frame("The opposing Charizard fainted!")
        self.assertEqual(ocr.read_bottom_banner(frame), "The opposing Charizard fainted!")

    def test_blank_frame_returns_empty_not_garbage(self):
        blank = np.zeros((450, 800, 3), dtype=np.uint8)
        self.assertEqual(ocr.read_bottom_banner(blank), "")

    def test_output_feeds_directly_into_battle_text_parser(self):
        """The whole point of this module - its output should be exactly
        what battle_text_parser.parse_line() expects, no glue code needed."""
        import battle_text_parser as btp
        frame = _make_banner_frame("A critical hit!")
        text = ocr.read_bottom_banner(frame)
        event = btp.parse_line(text)
        self.assertIsNotNone(event)
        self.assertEqual(event["event"], "critical_hit")


@unittest.skipUnless(_TESSERACT_OK and _FONT_PATH, "tesseract or a test font isn't available here")
class TestReadNameHpPlate(unittest.TestCase):
    def test_reads_name_and_exact_hp_fraction(self):
        frame = _make_plate_frame("Greninja", "155/155")
        name, cur, mx, pct = ocr.read_name_hp_plate(frame)
        self.assertEqual(name, "Greninja")
        self.assertEqual(cur, 155)
        self.assertEqual(mx, 155)
        self.assertEqual(pct, 100)

    def test_reads_name_and_percent_only(self):
        frame = _make_plate_frame("Charizard", "100%")
        name, cur, mx, pct = ocr.read_name_hp_plate(frame)
        self.assertEqual(name, "Charizard")
        self.assertIsNone(cur)
        self.assertIsNone(mx)
        self.assertEqual(pct, 100)

    def test_hp_fraction_missing_the_slash_is_still_recognized(self):
        """A real, observed OCR quirk (see ARCHITECTURE_HANDOFF.md): the
        '/' between two HP numbers sometimes doesn't survive OCR."""
        frame = _make_plate_frame("Primarina", "80 100")
        name, cur, mx, pct = ocr.read_name_hp_plate(frame)
        self.assertEqual(cur, 80)
        self.assertEqual(mx, 100)
        self.assertEqual(pct, 80)

    def test_blank_frame_returns_all_none(self):
        blank = np.zeros((450, 800, 3), dtype=np.uint8)
        self.assertEqual(ocr.read_name_hp_plate(blank), (None, None, None, None))


class TestIsolateTextEdgeCases(unittest.TestCase):
    """These don't need tesseract at all - just the cropping/guard logic."""

    def test_empty_crop_returns_none_not_a_crash(self):
        empty = np.zeros((0, 0, 3), dtype=np.uint8)
        self.assertIsNone(ocr._isolate_text(empty))

    def test_none_crop_returns_none(self):
        self.assertIsNone(ocr._isolate_text(None))


class TestCleanText(unittest.TestCase):
    def test_strips_non_battle_text_symbols(self):
        self.assertEqual(ocr._clean_text("© Greninja ♂"), "Greninja")

    def test_collapses_whitespace(self):
        self.assertEqual(ocr._clean_text("It's   super    effective!"), "It's super effective!")

    def test_none_input_returns_empty_string(self):
        self.assertEqual(ocr._clean_text(None), "")


# --- species_readable_in_frame() - the dynamic-camera visibility check ---
#
# Added to support analyze_matches.cross_check_reference_frame_visibility():
# Pokemon Champions' broadcast camera moves dynamically across the field, so
# a reference photo picked by nearest-timestamp alone (attach_reference_
# frames) isn't guaranteed to actually show the relevant side (see that
# function's docstring). These test the matching/scanning LOGIC by mocking
# pytesseract.image_to_string directly - not real synthetic frames like the
# classes above - because the whole point of VISIBILITY_SCAN_BANDS is that
# it hasn't been validated against real Pokemon Champions footage yet (none
# is bundled in this repo); testing the code's behavior against controlled
# text is honest about that, rather than pretending a PIL-rendered frame in
# one guessed layout would validate scan positions for a game we have no
# real captures of.

from unittest.mock import patch  # noqa: E402

import numpy as _np  # noqa: E402


def _blank_frame(h=100, w=100):
    return _np.zeros((h, w, 3), dtype=np.uint8)


class TestTextMatchesAny(unittest.TestCase):
    def test_exact_match(self):
        self.assertTrue(ocr._text_matches_any("Rillaboom used Grassy Glide", {"rillaboom"}))

    def test_no_match_at_all(self):
        self.assertFalse(ocr._text_matches_any("Whimsicott used Moonblast", {"rillaboom"}))

    def test_prefix_tolerant_of_ocr_truncation(self):
        """OCR frequently drops a trailing letter or two off real text -
        this should still count as a match, same tolerance
        pokemon_identity._fuzzy_match gives a real roster name."""
        self.assertTrue(ocr._text_matches_any("Rillaboo used Grassy Glide", {"rillaboom"}))

    def test_short_fragments_are_never_treated_as_a_match(self):
        """A short common word ('the', 'on') coincidentally overlapping the
        start of a real name must not count - both sides require len >= 4."""
        self.assertFalse(ocr._text_matches_any("on the field now", {"on"}))

    def test_empty_text_is_false(self):
        self.assertFalse(ocr._text_matches_any("", {"rillaboom"}))

    def test_multiple_candidate_names_any_one_matching_is_enough(self):
        self.assertTrue(ocr._text_matches_any(
            "Kingambit stands ready", {"rillaboom", "kingambit"}))


class TestSpeciesReadableInFrame(unittest.TestCase):
    def test_no_candidate_names_returns_false_without_scanning(self):
        with patch.object(ocr.pytesseract, "image_to_string") as mock_ocr:
            result = ocr.species_readable_in_frame(_blank_frame(), [])
        self.assertFalse(result)
        mock_ocr.assert_not_called()

    def test_match_found_in_first_scanned_band_short_circuits(self):
        with patch.object(ocr.pytesseract, "image_to_string", return_value="Rillaboom 68%") as mock_ocr:
            result = ocr.species_readable_in_frame(_blank_frame(200, 200), ["Rillaboom"])
        self.assertTrue(result)
        # Only the first band should have been OCR'd - no need to keep
        # scanning once a match is already found.
        self.assertEqual(mock_ocr.call_count, 1)

    def test_match_found_in_a_later_band_after_earlier_bands_miss(self):
        responses = iter(["", "", "Whimsicott 20%", "should not reach this"])
        with patch.object(ocr.pytesseract, "image_to_string", side_effect=lambda *a, **k: next(responses)):
            result = ocr.species_readable_in_frame(_blank_frame(200, 200), ["Whimsicott"])
        self.assertTrue(result)

    def test_no_band_contains_the_name_returns_false(self):
        with patch.object(ocr.pytesseract, "image_to_string", return_value="crowd cheering stadium"):
            result = ocr.species_readable_in_frame(_blank_frame(200, 200), ["Rillaboom"])
        self.assertFalse(result)

    def test_aliases_list_matches_on_any_candidate(self):
        """Callers can pass the guessed species plus any roster-conflict
        alternatives as candidates - a match on EITHER should count."""
        with patch.object(ocr.pytesseract, "image_to_string", return_value="Kingambit 55%"):
            result = ocr.species_readable_in_frame(_blank_frame(200, 200), ["Rillaboom", "Kingambit"])
        self.assertTrue(result)

    def test_empty_crop_region_is_skipped_not_raised(self):
        """A degenerate frame (region crop falls outside its bounds) makes
        _isolate_text return None for that region - must be skipped over,
        not raised on, and must not block scanning the remaining bands."""
        tiny_frame = _blank_frame(2, 2)
        with patch.object(ocr.pytesseract, "image_to_string", return_value="Rillaboom") as mock_ocr:
            result = ocr.species_readable_in_frame(tiny_frame, ["Rillaboom"])
        self.assertTrue(result)
        self.assertGreaterEqual(mock_ocr.call_count, 1)


if __name__ == "__main__":
    unittest.main()
