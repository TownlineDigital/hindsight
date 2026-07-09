"""
Tests for accuracy_addons/icon_template_matcher.py's OWN matching/hue-gate
logic (as opposed to tests/test_accuracy_addons_wiring.py, which only tests
analyze_matches.py's wiring around this module via monkeypatching - see that
file's own docstring for why the split exists).

Runs against REAL captured frames already present in this project's jobs/
directory (jobs/3e46bb33364c/match_frames/) - the same frames the module's
own docstring cites for its 2026-07-05 template additions and the hue-gate
false-positive fix, so a test failure here means the actual behavior no
longer matches what the docstring claims, not a synthetic-fixture drift.

Run: py -m unittest tests.test_icon_template_matcher -v   (from poc-starter/)
"""

import os
import unittest

import cv2
import numpy as np

from accuracy_addons import icon_template_matcher as itm

_HERE = os.path.dirname(os.path.abspath(__file__))
_JOB_DIR = os.path.join(_HERE, "..", "jobs", "3e46bb33364c", "match_frames")

# Move Info panel rows in match_1/b_00021.jpg (fractional top,bottom,left,
# right at 360x640) - Flower Trick/Triple Axel/Knock Off/Thunder Punch, the
# exact frame + rows the module docstring's 2026-07-05 addition cites.
_ROW_GRASS = (93 / 360, 117 / 360, 243 / 640, 267 / 640)
_ROW_ICE = (133 / 360, 157 / 360, 243 / 640, 267 / 640)
_ROW_DARK = (173 / 360, 197 / 360, 243 / 640, 267 / 640)
_ROW_ELECTRIC = (213 / 360, 237 / 360, 243 / 640, 267 / 640)


def _load(*parts):
    path = os.path.join(_JOB_DIR, *parts)
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(f"test fixture frame missing: {path}")
    return img


@unittest.skipUnless(os.path.isdir(_JOB_DIR), "real footage fixtures not present in this checkout")
class TestSelfMatchAllMoveTypeTemplates(unittest.TestCase):
    """Every VALIDATED_TEMPLATES entry should still identify correctly at
    its own source location - the "does the plumbing still work" check the
    module docstring describes performing during development. If one of
    these regresses, either the hue-gate got too strict or a template file
    changed."""

    @classmethod
    def setUpClass(cls):
        cls.frame = _load("match_1", "b_00021.jpg")

    def test_grass_self_match(self):
        self.assertEqual(itm.identify_move_type_icon(self.frame, region=_ROW_GRASS), "grass")

    def test_ice_self_match(self):
        self.assertEqual(itm.identify_move_type_icon(self.frame, region=_ROW_ICE), "ice")

    def test_dark_self_match(self):
        self.assertEqual(itm.identify_move_type_icon(self.frame, region=_ROW_DARK), "dark")

    def test_electric_self_match(self):
        self.assertEqual(itm.identify_move_type_icon(self.frame, region=_ROW_ELECTRIC), "electric")


@unittest.skipUnless(os.path.isdir(_JOB_DIR), "real footage fixtures not present in this checkout")
class TestHueGateRejectsRealFalsePositive(unittest.TestCase):
    """The exact false positive documented in the module docstring: the
    "ice" template (cyan) scored 0.96 - well above DEFAULT_THRESHOLD -
    against a completely different, differently-colored ("Discharge",
    Electric/yellow) icon in match_2/b_00014.jpg, purely from grayscale
    shape/luminance similarity. The hue gate must reject that and return
    "electric" (or, if electric's own shape score doesn't clear threshold
    at this exact sub-region, None) - "ice" specifically must never come
    back here."""

    @classmethod
    def setUpClass(cls):
        cls.frame = _load("match_2", "b_00014.jpg")

    def test_discharge_row_is_not_misidentified_as_ice(self):
        result = itm.identify_move_type_icon(self.frame, region=_ROW_DARK)
        self.assertNotEqual(result, "ice")

    def test_discharge_row_identifies_as_electric(self):
        result = itm.identify_move_type_icon(self.frame, region=_ROW_DARK)
        self.assertEqual(result, "electric")

    def test_hydro_pump_row_still_correctly_identifies_as_water(self):
        # Sanity check that the hue gate rejecting the false positive above
        # doesn't also collaterally break a genuine, correctly-colored
        # match elsewhere in the same different frame.
        result = itm.identify_move_type_icon(self.frame, region=_ROW_GRASS)
        self.assertEqual(result, "water")


class TestHueClose(unittest.TestCase):
    """_hue_close's own circular-wraparound and None-handling behavior,
    independent of any real frame - see module docstring for why None is
    treated as "can't verify, don't reject" rather than a veto."""

    def test_identical_hue_is_close(self):
        self.assertTrue(itm._hue_close(108, 108))

    def test_within_tolerance_is_close(self):
        self.assertTrue(itm._hue_close(100, 108, tolerance=20))

    def test_beyond_tolerance_is_not_close(self):
        self.assertFalse(itm._hue_close(25, 108, tolerance=20))

    def test_wraparound_near_179_and_0_is_close(self):
        # |178 - 2| = 176 raw, but circularly they're only 4 apart.
        self.assertTrue(itm._hue_close(178, 2, tolerance=10))

    def test_measured_none_does_not_reject(self):
        self.assertTrue(itm._hue_close(None, 108))

    def test_expected_none_does_not_reject(self):
        self.assertTrue(itm._hue_close(50, None))

    def test_exactly_at_tolerance_boundary_is_close(self):
        self.assertTrue(itm._hue_close(108, 128, tolerance=20))

    def test_just_beyond_tolerance_boundary_is_not_close(self):
        self.assertFalse(itm._hue_close(108, 129, tolerance=20))


class TestMedianHue(unittest.TestCase):
    """_median_hue's masking behavior on synthetic frames - real-frame hue
    values themselves are exercised via the false-positive test above; this
    isolates the masking/None-return logic on controlled input."""

    def test_solid_saturated_color_returns_its_hue(self):
        # Mid-brightness, fully-saturated green in BGR -> hue ~60 in
        # OpenCV's 0-179 range. Deliberately NOT pure (0,255,0) - that has
        # HSV value=255, which _median_hue's own v<235 mask (see its
        # docstring - excludes near-white/blown-out pixels) would itself
        # reject, making a "no data passes the mask" false negative rather
        # than testing the intended case.
        frame = np.zeros((24, 24, 3), dtype=np.uint8)
        frame[:, :] = (0, 180, 0)  # BGR green, value=180 comfortably inside the mask band
        hue = itm._median_hue(frame, (0, 0), (24, 24))
        self.assertIsNotNone(hue)
        self.assertAlmostEqual(hue, 60, delta=2)

    def test_all_dark_region_returns_none(self):
        frame = np.zeros((24, 24, 3), dtype=np.uint8)  # pure black -> v=0 everywhere
        hue = itm._median_hue(frame, (0, 0), (24, 24))
        self.assertIsNone(hue)

    def test_all_white_desaturated_region_returns_none(self):
        frame = np.full((24, 24, 3), 255, dtype=np.uint8)  # pure white -> s=0 everywhere
        hue = itm._median_hue(frame, (0, 0), (24, 24))
        self.assertIsNone(hue)

    def test_empty_crop_returns_none(self):
        frame = np.zeros((24, 24, 3), dtype=np.uint8)
        # top_left beyond frame bounds -> zero-size crop
        hue = itm._median_hue(frame, (100, 100), (24, 24))
        self.assertIsNone(hue)


@unittest.skipUnless(os.path.isdir(_JOB_DIR), "real footage fixtures not present in this checkout")
class TestIdentifyStatusIconStillWorks(unittest.TestCase):
    """The pre-existing burn-badge status detection (built before this
    segment's hue-gate addition) must still pass after wiring the same
    hue-check into identify_status_icon - a regression check, not new
    ground being broken."""

    def test_burn_badge_self_matches_on_its_source_frame(self):
        frame = _load("match_2", "b_00021.jpg")
        # Widened opponent-plate corner search box (top starts at 0.0, not
        # analyze_matches.py's _STATUS_BADGE_SEARCH_REGION top of 0.02 -
        # confirmed via direct matching that the real badge sits at
        # y=6/360=0.017, which _STATUS_BADGE_SEARCH_REGION's 0.02 top
        # clips by a single row, enough to drop match_icon_in_region's
        # score below DEFAULT_THRESHOLD even though the unrestricted
        # whole-frame match scores 0.9999 at that same location).
        result = itm.identify_status_icon(frame, region=(0.0, 0.20, 0.78, 1.0))
        self.assertEqual(result, "burn")


if __name__ == "__main__":
    unittest.main()
