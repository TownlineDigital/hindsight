"""
Tests for accuracy_addons/species_icon_matcher.py - see that module's own
HONEST CURRENT SCOPE docstring for the full real-validation story
(job 8c10092ac4a9, match 1). Headline: real testing found this module's
matching approach only correctly identifies about 1 of 6 real opponent
sprites even after fixing a real crop-framing bug and adding a real
tight-crop improvement - it is NOT wired into analyze_matches.py because
of that. These tests cover the pure MECHANICS (slicing, cropping,
compositing, merging) - they intentionally do NOT assert that
identify_species_icon/identify_opponent_team_from_column return the
CORRECT species on real footage, because real testing showed they
usually don't; asserting specific correct species here would misrepresent
the module's real, tested accuracy.
"""

import os
import shutil
import subprocess
import sys
import unittest

import numpy as np
import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "accuracy_addons"))
import species_icon_matcher as sim  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
TEMPLATES_DIR = os.path.join(ROOT, "accuracy_addons", "templates", "species")
VOD_PATH = os.path.join(ROOT, "jobs", "8c10092ac4a9", "vod.mp4")


def _solid_rgba(bgr, size=(40, 40), alpha=255):
    img = np.zeros((size[1], size[0], 4), dtype=np.uint8)
    img[:, :, 0] = bgr[0]
    img[:, :, 1] = bgr[1]
    img[:, :, 2] = bgr[2]
    img[:, :, 3] = alpha
    return img


class TestCompositeOnBackground(unittest.TestCase):

    def test_opaque_reference_ignores_background_arg(self):
        rgba = _solid_rgba((10, 20, 30), alpha=255)
        out = sim._composite_on_background(rgba, (200, 200, 200), (40, 40))
        self.assertTrue(np.allclose(out[:, :, 0], 10, atol=2))
        self.assertTrue(np.allclose(out[:, :, 1], 20, atol=2))
        self.assertTrue(np.allclose(out[:, :, 2], 30, atol=2))

    def test_fully_transparent_reference_becomes_pure_background(self):
        rgba = _solid_rgba((10, 20, 30), alpha=0)
        out = sim._composite_on_background(rgba, (200, 100, 50), (40, 40))
        self.assertTrue(np.allclose(out[:, :, 0], 200, atol=2))
        self.assertTrue(np.allclose(out[:, :, 1], 100, atol=2))
        self.assertTrue(np.allclose(out[:, :, 2], 50, atol=2))

    def test_resizes_to_requested_size(self):
        rgba = _solid_rgba((1, 2, 3), size=(10, 10))
        out = sim._composite_on_background(rgba, (0, 0, 0), (25, 60))
        self.assertEqual(out.shape[:2], (60, 25))


class TestTightCropToSprite(unittest.TestCase):

    def _panel_bgr(self, h=200, w=200):
        """A synthetic row band: solid roster-panel-hue background (BGR
        for hue~325deg, matching _BG_HUE_RANGE) with a bright, saturated
        rectangular "sprite" in the middle - a stand-in for a real sprite
        silhouette against the real magenta panel."""
        hsv = np.zeros((h, w, 3), dtype=np.uint8)
        hsv[:, :, 0] = int(325 / 2)   # ~325 degrees
        hsv[:, :, 1] = 150
        hsv[:, :, 2] = 120
        bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        # Bright green "sprite" block (well outside the background hue/dark mask)
        bgr[60:140, 60:140] = (40, 220, 40)
        return bgr

    def test_finds_the_sprite_shaped_component(self):
        img = self._panel_bgr()
        crop = sim._tight_crop_to_sprite(img)
        # Should be meaningfully smaller than the full 200x200 band and
        # roughly centered on the 80x80 bright block.
        self.assertLess(crop.shape[0] * crop.shape[1], img.shape[0] * img.shape[1])
        self.assertGreaterEqual(crop.shape[0], 60)
        self.assertGreaterEqual(crop.shape[1], 60)

    def test_all_background_falls_back_to_original(self):
        # A pure background-hue image has no real foreground component -
        # should return the input unchanged, not crash or return garbage.
        hsv = np.zeros((100, 100, 3), dtype=np.uint8)
        hsv[:, :, 0] = int(325 / 2)
        hsv[:, :, 1] = 150
        hsv[:, :, 2] = 120
        img = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        out = sim._tight_crop_to_sprite(img)
        self.assertEqual(out.shape, img.shape)


class TestSliceSpriteCrops(unittest.TestCase):

    def test_none_input_returns_all_none(self):
        self.assertEqual(sim.slice_sprite_crops(None), [None] * sim.MAX_ROWS)

    def test_slices_expected_row_count_from_synthetic_column(self):
        h, w = 2154, 586
        column = np.full((h, w, 3), 120, dtype=np.uint8)
        crops = sim.slice_sprite_crops(column)
        self.assertEqual(len(crops), sim.MAX_ROWS)
        for c in crops:
            self.assertIsNotNone(c)
            self.assertGreater(c.shape[0], 0)
            self.assertGreater(c.shape[1], 0)

    def test_row_beyond_crop_bottom_is_none(self):
        h, w = 200, 586
        column = np.full((h, w, 3), 120, dtype=np.uint8)
        crops = sim.slice_sprite_crops(column)
        self.assertIsNone(crops[-1])

    def test_dark_background_only_row_is_none(self):
        h, w = 2154, 586
        column = np.zeros((h, w, 3), dtype=np.uint8)
        crops = sim.slice_sprite_crops(column)
        self.assertTrue(all(c is None for c in crops))


class TestFilterManifestBySpecies(unittest.TestCase):

    def setUp(self):
        self.manifest = [
            {"species": "charizard", "filename": "a.png"},
            {"species": "kingambit", "filename": "b.png"},
            {"species": "Sneasler", "filename": "c.png"},
        ]

    def test_case_insensitive_filtering(self):
        out = sim.filter_manifest_by_species(self.manifest, ["Charizard", "sneasler"])
        names = {e["species"] for e in out}
        self.assertEqual(names, {"charizard", "Sneasler"})

    def test_empty_species_list_returns_empty(self):
        self.assertEqual(sim.filter_manifest_by_species(self.manifest, []), [])

    def test_unmatched_species_are_excluded(self):
        out = sim.filter_manifest_by_species(self.manifest, ["not-a-real-species"])
        self.assertEqual(out, [])


class TestIdentifySpeciesIconEdgeCases(unittest.TestCase):

    def test_none_sprite_returns_empty_list(self):
        self.assertEqual(sim.identify_species_icon(None), [])

    def test_empty_candidate_list_returns_empty(self):
        sprite = np.full((40, 40, 3), 100, dtype=np.uint8)
        self.assertEqual(sim.identify_species_icon(sprite, candidate_entries=[]), [])

    def test_missing_template_file_is_skipped_not_crashed(self):
        sprite = np.full((40, 40, 3), 100, dtype=np.uint8)
        entries = [{"species": "nonexistent", "filename": "does_not_exist_xyz.png",
                    "form": None, "shiny": False}]
        result = sim.identify_species_icon(sprite, candidate_entries=entries)
        self.assertEqual(result, [])

    def test_shiny_excluded_by_default(self):
        entries = [
            {"species": "a", "filename": "x.png", "form": None, "shiny": True},
        ]
        sprite = np.full((40, 40, 3), 100, dtype=np.uint8)
        result = sim.identify_species_icon(sprite, candidate_entries=entries, include_shiny=False)
        self.assertEqual(result, [])


class TestMergeColumnIdentifications(unittest.TestCase):

    def test_keeps_highest_confidence_per_row(self):
        crop_a = [{"row": 0, "species": "wrong", "form": None, "shiny": False,
                   "confidence": 0.4, "runner_up_margin": 0.05}]
        crop_b = [{"row": 0, "species": "right", "form": None, "shiny": False,
                   "confidence": 0.7, "runner_up_margin": 0.1}]
        merged = sim.merge_column_identifications([crop_a, crop_b])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["species"], "right")

    def test_merges_disjoint_rows_from_different_crops(self):
        crop_a = [{"row": 0, "species": "a", "form": None, "shiny": False,
                   "confidence": 0.5, "runner_up_margin": 0.05}]
        crop_b = [{"row": 1, "species": "b", "form": None, "shiny": False,
                   "confidence": 0.5, "runner_up_margin": 0.05}]
        merged = sim.merge_column_identifications([crop_a, crop_b])
        self.assertEqual({m["row"] for m in merged}, {0, 1})

    def test_empty_input_returns_empty(self):
        self.assertEqual(sim.merge_column_identifications([]), [])
        self.assertEqual(sim.merge_column_identifications([[], []]), [])


@unittest.skipUnless(
    os.path.isdir(TEMPLATES_DIR) and os.path.exists(os.path.join(TEMPLATES_DIR, "manifest.json")),
    "reference sprite library (accuracy_addons/templates/species/) not present in this checkout")
@unittest.skipUnless(os.path.exists(VOD_PATH), "jobs/8c10092ac4a9/vod.mp4 not present in this checkout")
class TestRealFootageRegression(unittest.TestCase):
    """Re-derives the real opponent sprite column from job 8c10092ac4a9's
    own vod.mp4 (match 1, ~70s - the timestamp confirmed via
    _looks_like_roster_panel to actually show the team-preview panel) via
    analyze_matches.crop_opponent_sprite_column(), then runs it through the
    real module end-to-end. This test intentionally does NOT assert
    specific correct species - see module docstring's HONEST CURRENT SCOPE
    for why (real testing found ~1/6 real rows correct). What it DOES
    assert: the real pipeline runs without crashing on real data, produces
    a well-formed result list, and returns AT MOST 6 rows (never
    fabricates extra ones) - basic real-data plumbing checks, not an
    accuracy claim."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, ROOT)
        import analyze_matches as am  # noqa: E402
        cls.am = am
        cls.tmpdir = os.path.join(os.path.dirname(__file__), "_tmp_species_matcher_test")
        os.makedirs(cls.tmpdir, exist_ok=True)
        frame_path = os.path.join(cls.tmpdir, "frame.jpg")
        ffmpeg = am.find_ffmpeg()
        subprocess.run(
            [ffmpeg, "-y", "-ss", "70", "-i", VOD_PATH, "-frames:v", "1", frame_path],
            check=True, capture_output=True)
        cls.column_paths = am.crop_opponent_sprite_column([(frame_path, 70.0)])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_real_pipeline_runs_and_returns_well_formed_results(self):
        self.assertTrue(self.column_paths,
                         "expected at least one opponent-sprite-column crop from the real frame")
        columns = [cv2.imread(p) for p in self.column_paths]
        all_results = [sim.identify_opponent_team_from_column(c) for c in columns]
        merged = sim.merge_column_identifications(all_results)
        self.assertLessEqual(len(merged), sim.MAX_ROWS)
        for r in merged:
            self.assertIn("row", r)
            self.assertIn("species", r)
            self.assertIsInstance(r["species"], str)
            self.assertIsInstance(r["confidence"], float)


if __name__ == "__main__":
    unittest.main()
