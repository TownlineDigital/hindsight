"""
Tests for accuracy_addons/team_preview_type_matcher.py - see that module's
own HONEST CURRENT SCOPE docstring for the full real-validation story
(job 8c10092ac4a9, match 1). Headline: real, multi-frame testing found this
module's candidate-list-recall property is solid (the true species was in
narrow_species_by_types' output 42/42 times across 7 real frames x 6 rows),
and full both-badge-correct identification - originally frame-sensitive
(3/6-5/6 across 7 real frames) - improved to 34/42 single-frame after the
_refine_oversized_badge_crop() fix for a diagnosed connected-component
merge bug (Kingambit's persistent steel-badge miss), and reaches a full,
exact 6/6 when that fix is combined with multi-frame majority-vote
aggregation. It is NOT wired into analyze_matches.py's read_roster() as a
standalone identifier yet - see module docstring for what's needed first.

These tests cover the pure MECHANICS (background segmentation, badge-
component finding, row slicing, crop refinement, narrowing logic) with
synthetic data, plus real-footage regression tests that assert the
property that actually held up under real testing: the true species is
always present in the narrowed candidate list. The single-frame real-
footage test intentionally does NOT assert that every row narrows to
exactly the right species on one arbitrary frame - real testing found that
varies frame to frame - but the multi-frame aggregation test does assert a
conservative floor for full-exact identification, since that combination
is the module's actual best-validated, most reliable mode of use.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "accuracy_addons"))
import team_preview_type_matcher as tpm  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
TEMPLATES_DIR = os.path.join(ROOT, "accuracy_addons", "templates", "team_preview_types")
SPECIES_TYPES_PATH = os.path.join(ROOT, "accuracy_addons", "data", "species_types.json")
VOD_PATH = os.path.join(ROOT, "jobs", "8c10092ac4a9", "vod.mp4")


def _panel_bgr(h=200, w=200):
    """A synthetic row band: solid roster-panel-hue background (BGR for
    hue~325deg, matching _BG_HUE_RANGE) - a stand-in for the real magenta
    team-preview panel, with no real badge content (subclasses/tests add
    their own foreground blocks on top of this)."""
    hsv = np.zeros((h, w, 3), dtype=np.uint8)
    hsv[:, :, 0] = int(325 / 2)
    hsv[:, :, 1] = 150
    hsv[:, :, 2] = 120
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


class TestBackgroundMask(unittest.TestCase):

    def test_pure_background_has_no_foreground(self):
        img = _panel_bgr()
        mask = tpm._background_mask(img)
        self.assertEqual(int(mask.max()), 0)

    def test_bright_block_is_foreground(self):
        img = _panel_bgr()
        img[60:140, 60:140] = (40, 220, 40)
        mask = tpm._background_mask(img)
        self.assertGreater(int(mask[100, 100]), 0)


class TestFindBadgeComponents(unittest.TestCase):

    def test_none_input_returns_empty(self):
        self.assertEqual(tpm.find_badge_components(None), [])

    def test_finds_two_square_badges(self):
        img = _panel_bgr(h=100, w=200)
        # Two ~30x30 "badges" side by side, in the top search fraction.
        img[10:40, 10:40] = (200, 200, 40)
        img[10:40, 60:90] = (40, 40, 200)
        boxes = tpm.find_badge_components(img)
        self.assertEqual(len(boxes), 2)
        # Sorted left to right.
        self.assertLess(boxes[0][0], boxes[1][0])

    def test_rejects_thin_strip_by_aspect_ratio(self):
        img = _panel_bgr(h=100, w=200)
        # A single real badge...
        img[10:40, 10:40] = (200, 200, 40)
        # ...plus a spurious thin horizontal strip (a real found artifact
        # in this module's own testing - a card-edge/divider), well past
        # the aspect-ratio bounds.
        img[45:55, 10:170] = (150, 150, 150)
        boxes = tpm.find_badge_components(img)
        self.assertEqual(len(boxes), 1)

    def test_rejects_components_below_min_size(self):
        img = _panel_bgr(h=100, w=200)
        img[10:18, 10:18] = (200, 200, 40)  # 8x8, below MIN_BADGE_SIDE_PX
        boxes = tpm.find_badge_components(img)
        self.assertEqual(boxes, [])

    def test_caps_at_max_badges_per_row(self):
        img = _panel_bgr(h=100, w=300)
        for x0 in (10, 60, 110, 160):
            img[10:40, x0:x0 + 30] = (200, 200, 40)
        boxes = tpm.find_badge_components(img)
        self.assertLessEqual(len(boxes), tpm.MAX_BADGES_PER_ROW)


class TestSliceBadgeRows(unittest.TestCase):

    def test_none_input_returns_all_none(self):
        self.assertEqual(tpm.slice_badge_rows(None), [None] * tpm.MAX_ROWS)

    def test_slices_expected_row_count_from_synthetic_column(self):
        h, w = 2154, 334
        column = np.full((h, w, 3), 120, dtype=np.uint8)
        rows = tpm.slice_badge_rows(column)
        self.assertEqual(len(rows), tpm.MAX_ROWS)
        for r in rows:
            self.assertIsNotNone(r)
            self.assertGreater(r.shape[0], 0)
            self.assertGreater(r.shape[1], 0)

    def test_too_short_column_yields_no_valid_rows(self):
        # ROW_TOP_FRAC/ROW_HEIGHT_FRAC are fractions of the crop's own
        # height, so every row shrinks proportionally as h shrinks - there
        # is no h where only the LAST row dips below MIN_ROW_HEIGHT_PX; it's
        # all-or-nothing. At h=100, each row's real height (~13.8px) is
        # below MIN_ROW_HEIGHT_PX (20), so every row should be None -
        # a real guard against treating noise as row content.
        h, w = 100, 334
        column = np.full((h, w, 3), 120, dtype=np.uint8)
        rows = tpm.slice_badge_rows(column)
        self.assertTrue(all(r is None for r in rows))

    def test_dark_background_only_row_is_none(self):
        h, w = 2154, 334
        column = np.zeros((h, w, 3), dtype=np.uint8)
        rows = tpm.slice_badge_rows(column)
        self.assertTrue(all(r is None for r in rows))

    def test_default_row_top_and_height_frac_match_module_constants(self):
        """Explicitly passing the module's own ROW_TOP_FRAC/ROW_HEIGHT_FRAC
        must produce identical output to the defaults - confirms the new
        override parameters (added 2026-07-08 for task #206, see
        analyze_matches.badge_column_geometry) don't change any existing
        caller's behavior when left unset."""
        h, w = 2154, 334
        column = np.full((h, w, 3), 120, dtype=np.uint8)
        default_rows = tpm.slice_badge_rows(column)
        explicit_rows = tpm.slice_badge_rows(column, row_top_frac=tpm.ROW_TOP_FRAC,
                                              row_height_frac=tpm.ROW_HEIGHT_FRAC)
        for d, e in zip(default_rows, explicit_rows):
            if d is None or e is None:
                self.assertEqual(d is None, e is None)
            else:
                np.testing.assert_array_equal(d, e)

    def test_landscape_override_divides_evenly_with_no_header_gap(self):
        """analyze_matches.LANDSCAPE_ROW_TOP_FRAC=0.0 / LANDSCAPE_ROW_HEIGHT_
        FRAC=1/6 (a landscape-video-specific override, see
        analyze_matches.badge_column_geometry's own docstring for the real,
        measured bug this fixes) should slice the crop into 6 EQUAL bands
        starting right at the top - no header gap, unlike the portrait
        defaults above (which reserve ~13.6% of height before row 1)."""
        h, w = 540, 200
        column = np.full((h, w, 3), 120, dtype=np.uint8)
        rows = tpm.slice_badge_rows(column, row_top_frac=0.0, row_height_frac=1 / 6)
        self.assertEqual(len(rows), tpm.MAX_ROWS)
        for r in rows:
            self.assertIsNotNone(r)
            self.assertEqual(r.shape[0], h // tpm.MAX_ROWS)

    def test_override_changes_row_boundaries_vs_default(self):
        """A row_top_frac=0.0 override should start row 0 earlier than the
        portrait default (which reserves a header gap) - confirms the
        override actually reaches the slicing math, not just accepted and
        ignored."""
        h, w = 2154, 334
        # Distinct colors above/below where the default's row-1 top would
        # land, so we can tell whether row 0's content shifted upward.
        column = np.zeros((h, w, 3), dtype=np.uint8)
        default_row_top_px = int(tpm.ROW_TOP_FRAC * h)
        column[:default_row_top_px, :] = 200          # bright "header" band
        column[default_row_top_px:, :] = 120           # bright "row content" band
        default_rows = tpm.slice_badge_rows(column)
        override_rows = tpm.slice_badge_rows(column, row_top_frac=0.0, row_height_frac=1 / 6)
        # Default row 0 should sit entirely in the dimmer "row content" band
        # (mean == 120); the override's row 0 starts at y=0 and should
        # include some of the brighter "header" band, raising its mean.
        self.assertAlmostEqual(float(default_rows[0].mean()), 120.0, places=3)
        self.assertGreater(float(override_rows[0].mean()), float(default_rows[0].mean()))


class TestIdentifyBadgeTypeEdgeCases(unittest.TestCase):

    def test_none_badge_returns_empty_list(self):
        self.assertEqual(tpm.identify_badge_type(None), [])

    def test_empty_templates_returns_empty_list(self):
        badge = np.full((40, 40, 3), 100, dtype=np.uint8)
        self.assertEqual(tpm.identify_badge_type(badge, templates={}), [])

    def test_matches_identical_synthetic_template(self):
        badge = np.full((40, 40, 3), 100, dtype=np.uint8)
        gray = cv2.cvtColor(cv2.resize(badge, tpm.MATCH_SIZE), cv2.COLOR_BGR2GRAY)
        ranked = tpm.identify_badge_type(badge, templates={"testtype": [gray]})
        self.assertEqual(ranked[0][1], "testtype")
        self.assertGreater(ranked[0][0], 0.99)


class TestAverageColor(unittest.TestCase):

    def test_solid_color_returns_that_color(self):
        img = np.full((50, 50, 3), (10, 20, 30), dtype=np.uint8)
        avg = tpm._average_color(img)
        np.testing.assert_allclose(avg, [10, 20, 30], atol=0.5)

    def test_non_square_image_still_averages_correctly(self):
        img = np.full((80, 30, 3), (100, 150, 200), dtype=np.uint8)
        avg = tpm._average_color(img)
        np.testing.assert_allclose(avg, [100, 150, 200], atol=0.5)


class TestColorSimilarity(unittest.TestCase):

    def test_identical_colors_are_perfectly_similar(self):
        c = np.array([50.0, 60.0, 70.0])
        self.assertAlmostEqual(tpm._color_similarity(c, c), 1.0, places=5)

    def test_distance_at_scale_boundary_is_zero(self):
        c1 = np.array([0.0, 0.0, 0.0])
        c2 = np.array([0.0, 0.0, tpm.COLOR_DISTANCE_SCALE])
        self.assertAlmostEqual(tpm._color_similarity(c1, c2), 0.0, places=5)

    def test_distance_beyond_scale_is_clamped_to_zero_not_negative(self):
        c1 = np.array([0.0, 0.0, 0.0])
        c2 = np.array([0.0, 0.0, tpm.COLOR_DISTANCE_SCALE * 3])
        self.assertEqual(tpm._color_similarity(c1, c2), 0.0)

    def test_partial_distance_scales_linearly(self):
        c1 = np.array([0.0, 0.0, 0.0])
        half_dist = tpm.COLOR_DISTANCE_SCALE / 2.0
        c2 = np.array([0.0, 0.0, half_dist])
        self.assertAlmostEqual(tpm._color_similarity(c1, c2), 0.5, places=5)


class TestLoadTypeTemplateColors(unittest.TestCase):
    """Uses tiny temp dirs of solid-color synthetic PNGs rather than the
    real templates dir, so these tests don't depend on which real types
    happen to be captured yet. Each test resets the module-level
    _TEMPLATE_COLOR_CACHE first, since load_type_template_colors() caches
    across calls and ignores templates_dir on a cache hit (see
    test_second_call_returns_cached_result_without_rereading_dir below,
    which asserts that behavior directly)."""

    def setUp(self):
        self._original_cache = tpm._TEMPLATE_COLOR_CACHE
        tpm._TEMPLATE_COLOR_CACHE = None
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        tpm._TEMPLATE_COLOR_CACHE = self._original_cache
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_nonexistent_dir_returns_empty_dict(self):
        result = tpm.load_type_template_colors(templates_dir=os.path.join(self.tmpdir, "nope"))
        self.assertEqual(result, {})

    def test_loads_average_color_for_single_template(self):
        img = np.full((64, 64, 3), (10, 20, 30), dtype=np.uint8)
        cv2.imwrite(os.path.join(self.tmpdir, "type_testred.png"), img)
        result = tpm.load_type_template_colors(templates_dir=self.tmpdir)
        self.assertIn("testred", result)
        np.testing.assert_allclose(result["testred"], [10, 20, 30], atol=0.5)

    def test_averages_across_multiple_templates_of_same_type_including_b_suffix(self):
        img1 = np.full((64, 64, 3), (0, 0, 0), dtype=np.uint8)
        img2 = np.full((64, 64, 3), (100, 100, 100), dtype=np.uint8)
        cv2.imwrite(os.path.join(self.tmpdir, "type_testblue.png"), img1)
        cv2.imwrite(os.path.join(self.tmpdir, "type_testblue_b.png"), img2)
        result = tpm.load_type_template_colors(templates_dir=self.tmpdir)
        self.assertIn("testblue", result)
        np.testing.assert_allclose(result["testblue"], [50, 50, 50], atol=0.5)

    def test_second_call_returns_cached_result_without_rereading_dir(self):
        img = np.full((64, 64, 3), (5, 5, 5), dtype=np.uint8)
        cv2.imwrite(os.path.join(self.tmpdir, "type_testgreen.png"), img)
        first = tpm.load_type_template_colors(templates_dir=self.tmpdir)
        # A second call against a DIFFERENT (empty) dir should still return
        # the cached first result, since the cache doesn't key on templates_dir.
        other_dir = tempfile.mkdtemp()
        try:
            second = tpm.load_type_template_colors(templates_dir=other_dir)
        finally:
            shutil.rmtree(other_dir, ignore_errors=True)
        self.assertIs(second, first)


class TestIdentifyBadgeTypeWithColor(unittest.TestCase):

    def test_empty_shape_ranking_returns_empty_list(self):
        badge = np.full((40, 40, 3), 100, dtype=np.uint8)
        result = tpm.identify_badge_type_with_color(badge, templates={})
        self.assertEqual(result, [])

    def test_no_template_colors_returns_shape_ranking_unmodified(self):
        badge = np.full((40, 40, 3), 100, dtype=np.uint8)
        gray = cv2.cvtColor(cv2.resize(badge, tpm.MATCH_SIZE), cv2.COLOR_BGR2GRAY)
        shape_only = tpm.identify_badge_type(badge, templates={"testtype": [gray]})
        with_color = tpm.identify_badge_type_with_color(
            badge, templates={"testtype": [gray]}, template_colors={})
        self.assertEqual(with_color, shape_only)

    def test_color_agreement_adds_a_positive_bonus(self):
        # A badge whose shape template is a mediocre (not perfect) match, so
        # there's room above it for a bonus to matter. Flat/constant-color
        # crops are a known TM_CCOEFF_NORMED degenerate case (zero template
        # variance can score a spurious 1.0 - see the module's own
        # find-badge-components merge-bug test comment), so - matching this
        # file's existing convention elsewhere - real per-pixel noise
        # texture is used instead of a flat fill to get a genuine,
        # non-degenerate imperfect match.
        rng = np.random.RandomState(7)
        base = rng.randint(40, 220, size=(40, 40, 3)).astype(np.uint8)
        gray = cv2.cvtColor(cv2.resize(base, tpm.MATCH_SIZE), cv2.COLOR_BGR2GRAY)
        templates = {"testtype": [gray]}
        # The actual badge crop: same base texture with a touch of extra
        # noise, so it's similar but not pixel-identical to the template.
        noise = rng.randint(-20, 20, size=(40, 40, 3))
        badge = np.clip(base.astype(int) + noise, 0, 255).astype(np.uint8)
        shape_only = tpm.identify_badge_type(badge, templates=templates)
        self.assertTrue(shape_only and shape_only[0][0] < 1.0,
                         f"test setup expects an imperfect shape score, got {shape_only}")
        # Exact color match (distance 0) -> maximum possible bonus.
        template_colors = {"testtype": tpm._average_color(badge)}
        with_color = tpm.identify_badge_type_with_color(
            badge, templates=templates, template_colors=template_colors)
        self.assertGreater(with_color[0][0], shape_only[0][0])

    def test_color_disagreement_never_lowers_the_score(self):
        badge = np.full((40, 40, 3), (60, 60, 200), dtype=np.uint8)
        gray = cv2.cvtColor(cv2.resize(badge, tpm.MATCH_SIZE), cv2.COLOR_BGR2GRAY)
        templates = {"testtype": [gray]}
        shape_only = tpm.identify_badge_type(badge, templates=templates)
        # A wildly different reference color (max possible BGR distance).
        template_colors = {"testtype": np.array([255.0, 255.0, 0.0])}
        with_color = tpm.identify_badge_type_with_color(
            badge, templates=templates, template_colors=template_colors)
        self.assertGreaterEqual(with_color[0][0], shape_only[0][0])

    def test_bonus_never_pushes_score_above_one(self):
        badge = np.full((40, 40, 3), (60, 60, 200), dtype=np.uint8)
        gray = cv2.cvtColor(cv2.resize(badge, tpm.MATCH_SIZE), cv2.COLOR_BGR2GRAY)
        templates = {"testtype": [gray]}
        template_colors = {"testtype": tpm._average_color(badge)}
        with_color = tpm.identify_badge_type_with_color(
            badge, templates=templates, template_colors=template_colors)
        self.assertLessEqual(with_color[0][0], 1.0)


class TestIdentifyRowTypes(unittest.TestCase):

    def test_none_row_finds_no_badges(self):
        result = tpm.identify_row_types(None)
        self.assertEqual(result, {"num_badges_found": 0, "identified_types": []})

    def test_recovers_second_badge_when_component_is_merged_oversized(self):
        """Integration-level regression test for the real, diagnosed
        Kingambit bug (see module docstring's ROOT CAUSE section): builds a
        synthetic row where the second badge's true pixels sit inside a
        much bigger noisy connected-component blob (simulating the real
        background-segmentation merge artifact), and confirms
        identify_row_types() still recovers the correct type via
        _refine_oversized_badge_crop() rather than either missing it or
        scoring the malformed box directly."""
        # NOTE: badge fills use a fixed-seed random-noise texture, not a
        # flat color or simple 2-tone block. Two flat/simple-pattern crops
        # of similar overall brightness can score a near-tie (or even
        # invert) under cv2.matchTemplate's TM_CCOEFF_NORMED, since that's
        # a real degenerate/near-degenerate case for low-variance content
        # (verified directly while writing this test) - real captured badge
        # templates always have plenty of genuine texture, so this only
        # matters for synthetic test fixtures with 2+ competing templates.
        # Uncorrelated random noise gives a clean, robust score separation
        # instead (own template ~0.9+, other type's template ~0.0-0.2).
        def _noise_patch(h, w, seed):
            return np.random.RandomState(seed).randint(40, 220, size=(h, w, 3)).astype(np.uint8)

        row_bgr = _panel_bgr(h=120, w=200)
        # A normal, correctly-sized first badge - kept well clear of the
        # second badge's search window (x < 35, see below) so the local
        # recovery search below can never bleed into it.
        row_bgr[10:40, 5:30] = _noise_patch(30, 25, seed=1)
        # A big noisy foreground blob (simulating a real merge artifact)
        # that CONTAINS the true second badge's pixels somewhere inside it,
        # at a size matching one of REFINE_SIZE_OPTIONS exactly.
        row_bgr[5:95, 60:140] = (80, 80, 80)
        row_bgr[20:56, 71:108] = _noise_patch(36, 37, seed=2)

        def _template_for(patch_bgr):
            return cv2.cvtColor(cv2.resize(patch_bgr, tpm.MATCH_SIZE), cv2.COLOR_BGR2GRAY)

        templates = {
            "firecolor": [_template_for(_noise_patch(30, 25, seed=1))],
            "teststeel": [_template_for(_noise_patch(36, 37, seed=2))],
        }
        original = tpm.load_type_templates
        tpm.load_type_templates = lambda *a, **k: templates
        try:
            boxes = tpm.find_badge_components(row_bgr)
            self.assertEqual(len(boxes), 2, f"test setup expected exactly 2 components, got {boxes}")
            (_, _, w0, h0), (_, _, w1, h1) = boxes
            self.assertTrue(
                w1 > w0 * tpm.BADGE_SIZE_ANOMALY_RATIO or h1 > h0 * tpm.BADGE_SIZE_ANOMALY_RATIO,
                "test setup should produce an anomalously large second box (got "
                f"box0={boxes[0]}, box1={boxes[1]})")
            result = tpm.identify_row_types(row_bgr)
        finally:
            tpm.load_type_templates = original
        self.assertEqual(result["num_badges_found"], 2)
        self.assertIn("firecolor", result["identified_types"])
        self.assertIn("teststeel", result["identified_types"])


class TestIdentifyRowTypesColorCheckFlag(unittest.TestCase):
    """Wiring test: confirms use_color_check routes identify_row_types
    through identify_badge_type_with_color instead of identify_badge_type,
    and that the default (False) preserves the prior shape-only behavior
    exactly (no color scorer involved at all)."""

    def test_use_color_check_flag_selects_the_color_aware_scorer(self):
        row_bgr = _panel_bgr(h=120, w=200)
        row_bgr[10:40, 5:30] = (60, 60, 200)
        gray = cv2.cvtColor(
            cv2.resize(np.full((30, 25, 3), (60, 60, 200), dtype=np.uint8), tpm.MATCH_SIZE),
            cv2.COLOR_BGR2GRAY)
        shape_templates = {"realtype": [gray]}

        original_load = tpm.load_type_templates
        original_color_fn = tpm.identify_badge_type_with_color
        tpm.load_type_templates = lambda *a, **k: shape_templates
        tpm.identify_badge_type_with_color = lambda badge_bgr, **kwargs: [(0.99, "colorfake")]
        try:
            result_default = tpm.identify_row_types(row_bgr)
            result_color = tpm.identify_row_types(row_bgr, use_color_check=True)
        finally:
            tpm.load_type_templates = original_load
            tpm.identify_badge_type_with_color = original_color_fn

        self.assertIn("realtype", result_default["identified_types"])
        self.assertNotIn("colorfake", result_default["identified_types"])
        self.assertIn("colorfake", result_color["identified_types"])
        self.assertNotIn("realtype", result_color["identified_types"])


class TestRefineOversizedBadgeCrop(unittest.TestCase):
    """Isolated mechanics tests for _refine_oversized_badge_crop() itself,
    independent of find_badge_components/identify_row_types - see
    TestIdentifyRowTypes.test_recovers_second_badge_when_component_is_merged_oversized
    for the end-to-end integration test."""

    def test_none_row_returns_zero_none(self):
        self.assertEqual(tpm._refine_oversized_badge_crop(None, (0, 0, 10, 10)), (0.0, None))

    def test_no_templates_returns_zero_none(self):
        row_bgr = _panel_bgr(h=120, w=200)
        self.assertEqual(
            tpm._refine_oversized_badge_crop(row_bgr, (10, 10, 30, 30), templates={}),
            (0.0, None))

    def test_recovers_correct_type_from_generously_oversized_box(self):
        row_bgr = _panel_bgr(h=120, w=200)
        # The true badge, sized to exactly match one REFINE_SIZE_OPTIONS
        # entry (37 wide, 36 tall), embedded well inside a much larger
        # malformed box passed in below (simulating the real merge artifact
        # - see module docstring's ROOT CAUSE section).
        row_bgr[20:56, 70:107] = (60, 60, 200)
        gray = cv2.cvtColor(
            cv2.resize(np.full((36, 37, 3), (60, 60, 200), dtype=np.uint8), tpm.MATCH_SIZE),
            cv2.COLOR_BGR2GRAY)
        templates = {"teststeel": [gray]}
        score, ttype = tpm._refine_oversized_badge_crop(row_bgr, (55, 5, 70, 90), templates=templates)
        self.assertEqual(ttype, "teststeel")
        self.assertGreaterEqual(score, tpm.MIN_BADGE_MATCH_SCORE)

    def test_degenerate_box_near_edge_does_not_crash(self):
        row_bgr = _panel_bgr(h=40, w=40)
        gray = np.full(tpm.MATCH_SIZE, 100, dtype=np.uint8)
        # A box that leaves no room for any REFINE_SIZE_OPTIONS window
        # within this tiny row - should degrade gracefully, not raise.
        score, ttype = tpm._refine_oversized_badge_crop(
            row_bgr, (35, 35, 5, 5), templates={"testtype": [gray]})
        self.assertIsInstance(score, float)


class TestIdentifyRowTypesMultiFrame(unittest.TestCase):
    """Pure logic tests for the majority-vote aggregation, using
    hand-built identify_row_types()-shaped dicts (not real images) so the
    voting RULE itself is tested independently of badge detection/matching.
    We call the real function but stub identify_row_types via a fake
    row_bgr_list of pre-baked sentinel objects and monkeypatch
    identify_row_types for the duration of each test - simplest way to
    drive the aggregation logic deterministically."""

    def _run_with_fake_frame_results(self, fake_results, **kwargs):
        original = tpm.identify_row_types
        it = iter(fake_results)
        tpm.identify_row_types = (
            lambda row_bgr, min_score=tpm.MIN_BADGE_MATCH_SCORE, use_color_check=False: next(it))
        try:
            # One sentinel per fake result - only the COUNT and non-None-ness matters.
            row_bgr_list = [object() for _ in fake_results]
            return tpm.identify_row_types_multi_frame(row_bgr_list, **kwargs)
        finally:
            tpm.identify_row_types = original

    def test_empty_list_returns_zeroed_result(self):
        result = tpm.identify_row_types_multi_frame([])
        self.assertEqual(result["num_badges_found"], 0)
        self.assertEqual(result["identified_types"], [])
        self.assertEqual(result["n_frames_used"], 0)

    def test_none_entries_are_skipped(self):
        result = tpm.identify_row_types_multi_frame([None, None])
        self.assertEqual(result["n_frames_used"], 0)

    def test_majority_confirms_type_seen_in_most_frames(self):
        fake = [
            {"num_badges_found": 2, "identified_types": ["fire", "dark"]},
            {"num_badges_found": 2, "identified_types": ["fire", "dark"]},
            {"num_badges_found": 2, "identified_types": ["fire"]},  # missed "dark" this frame
        ]
        result = self._run_with_fake_frame_results(fake)
        # Majority threshold for n=3 is 2 - both "fire" (3/3) and "dark" (2/3) qualify.
        self.assertEqual(result["identified_types"], ["dark", "fire"])
        self.assertEqual(result["n_frames_used"], 3)

    def test_minority_type_is_filtered_out(self):
        fake = [
            {"num_badges_found": 1, "identified_types": ["water"]},
            {"num_badges_found": 1, "identified_types": ["water"]},
            {"num_badges_found": 1, "identified_types": ["water"]},
            {"num_badges_found": 1, "identified_types": []},  # noise: nothing classified this frame
            {"num_badges_found": 2, "identified_types": ["grass"]},  # a single noisy frame's false read
        ]
        result = self._run_with_fake_frame_results(fake)
        # "grass" only appears in 1/5 frames - below majority (3) - must not be confirmed.
        self.assertNotIn("grass", result["identified_types"])
        self.assertIn("water", result["identified_types"])

    def test_badge_count_mode_resolves_noisy_minority(self):
        fake = [
            {"num_badges_found": 1, "identified_types": ["water"]},
            {"num_badges_found": 1, "identified_types": ["water"]},
            {"num_badges_found": 1, "identified_types": ["water"]},
            {"num_badges_found": 2, "identified_types": ["water"]},
            {"num_badges_found": 2, "identified_types": ["water"]},
        ]
        result = self._run_with_fake_frame_results(fake)
        # 3 frames said 1 badge, 2 frames said 2 - mode is 1.
        self.assertEqual(result["num_badges_found"], 1)
        self.assertEqual(result["badge_count_votes"], {1: 3, 2: 2})

    def test_badge_count_tie_breaks_toward_larger_count(self):
        fake = [
            {"num_badges_found": 1, "identified_types": ["water"]},
            {"num_badges_found": 2, "identified_types": ["water"]},
        ]
        result = self._run_with_fake_frame_results(fake)
        # Tied 1-1 - deliberately favors the LARGER count (safer: avoids
        # wrongly triggering the stricter exact-single-type narrowing rule
        # on a real dual-typed species - see function docstring).
        self.assertEqual(result["num_badges_found"], 2)

    def test_custom_min_frame_agreement_is_respected(self):
        fake = [
            {"num_badges_found": 1, "identified_types": ["water"]},
            {"num_badges_found": 1, "identified_types": []},
            {"num_badges_found": 1, "identified_types": []},
        ]
        # With the default majority (2/3), "water" (1/3) would NOT be confirmed.
        result_default = self._run_with_fake_frame_results(fake)
        self.assertNotIn("water", result_default["identified_types"])
        # With min_frame_agreement=1, a single frame's read is enough.
        result_lenient = self._run_with_fake_frame_results(fake, min_frame_agreement=1)
        self.assertIn("water", result_lenient["identified_types"])

    def test_large_pool_uses_capped_threshold_not_a_growing_majority(self):
        """2026-07-08 real-production fix: pooling frames from all 5
        ROSTER_SEARCH_ATTEMPTS can produce a large n where most frames are
        transitional noise and a true signal only shows up a handful of
        times - a plain majority ((n//2)+1) would never confirm it. This
        mirrors the real measured shape found in job 8c10092ac4a9 match 4
        (n=18, a real type confirmed in exactly 3 of 18 pooled frames)."""
        fake = (
            [{"num_badges_found": 1, "identified_types": ["dragon"]}] * 3 +
            [{"num_badges_found": 1, "identified_types": []}] * 15
        )
        self.assertEqual(len(fake), 18)
        result = self._run_with_fake_frame_results(fake)
        # Uncapped majority for n=18 would be 10 - "dragon" (3/18) would
        # never clear that. The capped default should still confirm it.
        self.assertIn("dragon", result["identified_types"])

    def test_large_pool_cap_still_filters_out_a_two_vote_false_positive(self):
        """Real measured evidence (job 8c10092ac4a9 match 4, Corviknight's
        row): a spurious type scoring high enough to hit 2/18 by
        coincidence must NOT be confirmed at the chosen cap, since a false
        positive here can wrongly EXCLUDE the true species from
        narrow_species_by_types' exact-pair match - the more dangerous
        failure mode this module is built to avoid."""
        fake = (
            [{"num_badges_found": 1, "identified_types": ["dragon"]}] * 2 +
            [{"num_badges_found": 1, "identified_types": []}] * 16
        )
        result = self._run_with_fake_frame_results(fake)
        self.assertNotIn("dragon", result["identified_types"])

    def test_small_pool_is_unaffected_by_the_cap(self):
        """For a small, homogeneous batch (the already-validated real-
        footage case, n=7), the cap must not raise the threshold above the
        natural majority - only large pools should be affected."""
        fake = [
            {"num_badges_found": 1, "identified_types": ["water"]},
            {"num_badges_found": 1, "identified_types": ["water"]},
            {"num_badges_found": 1, "identified_types": []},
        ]
        # Natural majority for n=3 is 2 (below MAX_FRAME_AGREEMENT_CAP=3) -
        # "water" (2/3) should still be confirmed, same as before the cap
        # existed.
        result = self._run_with_fake_frame_results(fake)
        self.assertIn("water", result["identified_types"])

    def test_result_feeds_directly_into_narrow_species_by_types(self):
        types_map = {"mono_water": ["water"], "fire_dark": ["dark", "fire"]}
        fake = [
            {"num_badges_found": 1, "identified_types": ["water"]},
            {"num_badges_found": 1, "identified_types": ["water"]},
            {"num_badges_found": 1, "identified_types": ["water"]},
        ]
        agg = self._run_with_fake_frame_results(fake)
        candidates = tpm.narrow_species_by_types(
            agg["identified_types"], agg["num_badges_found"], types_map)
        self.assertEqual(candidates, ["mono_water"])


class TestNarrowSpeciesByTypes(unittest.TestCase):
    """Pure logic tests against a small synthetic species->types map - no
    dependency on the real species_types.json file."""

    def setUp(self):
        self.types_map = {
            "mono_water_a": ["water"],
            "mono_water_b": ["water"],
            "mono_fire": ["fire"],
            "fire_dark": ["dark", "fire"],
            "fire_psychic": ["fire", "psychic"],
            "dark_steel": ["dark", "steel"],
        }

    def test_empty_identified_types_returns_everything(self):
        out = tpm.narrow_species_by_types([], 0, self.types_map)
        self.assertEqual(set(out), set(self.types_map))

    def test_one_badge_found_requires_exact_mono_type(self):
        out = tpm.narrow_species_by_types(["water"], 1, self.types_map)
        self.assertEqual(set(out), {"mono_water_a", "mono_water_b"})
        # A dual-typed species is never a valid answer for a mono-type read.
        self.assertNotIn("fire_dark", out)

    def test_two_badges_both_classified_requires_exact_pair(self):
        out = tpm.narrow_species_by_types(["fire", "dark"], 2, self.types_map)
        self.assertEqual(out, ["fire_dark"])

    def test_two_badges_one_classified_is_partial_contains_match(self):
        out = tpm.narrow_species_by_types(["fire"], 2, self.types_map)
        self.assertEqual(set(out), {"mono_fire", "fire_dark", "fire_psychic"})

    def test_real_species_never_excluded_for_its_own_true_types(self):
        # For every synthetic species, narrowing on its OWN real type
        # signature (with the matching num_badges_found) must include it.
        for species, types in self.types_map.items():
            n_badges = 1 if len(types) == 1 else 2
            out = tpm.narrow_species_by_types(types, n_badges, self.types_map)
            self.assertIn(species, out)


@unittest.skipUnless(
    os.path.isdir(TEMPLATES_DIR), "type-badge templates not present in this checkout")
@unittest.skipUnless(
    os.path.exists(SPECIES_TYPES_PATH), "species_types.json not present in this checkout")
class TestLoaders(unittest.TestCase):

    def test_load_type_templates_returns_nonempty(self):
        templates = tpm.load_type_templates()
        self.assertGreater(len(templates), 0)
        for type_name, refs in templates.items():
            self.assertIsInstance(type_name, str)
            self.assertGreater(len(refs), 0)

    def test_load_species_types_has_212_legal_species(self):
        species_types = tpm.load_species_types()
        self.assertEqual(len(species_types), 212)
        for species, types in species_types.items():
            self.assertIn(len(types), (1, 2))


@unittest.skipUnless(
    os.path.isdir(TEMPLATES_DIR), "type-badge templates not present in this checkout")
@unittest.skipUnless(
    os.path.exists(SPECIES_TYPES_PATH), "species_types.json not present in this checkout")
@unittest.skipUnless(os.path.exists(VOD_PATH), "jobs/8c10092ac4a9/vod.mp4 not present in this checkout")
class TestRealFootageRegression(unittest.TestCase):
    """Re-derives the real opponent badge column from job 8c10092ac4a9's own
    vod.mp4 (match 1, ~70s) via analyze_matches.crop_opponent_badge_column(),
    at the same 1024px-wide scale the production pipeline actually samples
    at, then runs it through the real module end-to-end.

    Ground truth for this match's 6 opponent rows (confirmed in
    ARCHITECTURE_HANDOFF.md section 2j): Delphox, Sneasler, Incineroar,
    Kingambit, Blastoise, Sinistcha.

    This test asserts the ONE property that held up under real, repeated
    (7-frame) testing: the true species is always present in
    narrow_species_by_types' candidate list. It intentionally does NOT
    assert that any row narrows to exactly one species, or that both real
    badges get identified - see module docstring's HONEST CURRENT SCOPE for
    why (real testing found that varies frame to frame, 3/6-5/6)."""

    EXPECTED_SPECIES = [
        "delphox", "sneasler", "incineroar", "kingambit", "blastoise", "sinistcha",
    ]

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, ROOT)
        import analyze_matches as am  # noqa: E402
        cls.am = am
        cls.tmpdir = os.path.join(os.path.dirname(__file__), "_tmp_type_matcher_test")
        os.makedirs(cls.tmpdir, exist_ok=True)
        raw_frame = os.path.join(cls.tmpdir, "frame_raw.png")
        ffmpeg = am.find_ffmpeg()
        subprocess.run(
            [ffmpeg, "-y", "-ss", "70", "-i", VOD_PATH, "-frames:v", "1", raw_frame],
            check=True, capture_output=True)
        # Match production's actual roster-frame sampling scale (ROSTER_SCALE_W)
        # rather than native resolution - the badge-component size thresholds
        # are tuned in pixels, so scale matters.
        img = cv2.imread(raw_frame)
        h, w = img.shape[:2]
        scale = am.ROSTER_SCALE_W / w
        resized = cv2.resize(img, (am.ROSTER_SCALE_W, int(round(h * scale))),
                              interpolation=cv2.INTER_AREA)
        frame_path = os.path.join(cls.tmpdir, "frame.png")
        cv2.imwrite(frame_path, resized)
        cls.column_paths = am.crop_opponent_badge_column([(frame_path, 70.0)])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_real_pipeline_runs_and_true_species_always_a_candidate(self):
        self.assertTrue(self.column_paths,
                         "expected at least one opponent-badge-column crop from the real frame")
        column = cv2.imread(self.column_paths[0])
        rows = tpm.slice_badge_rows(column)
        self.assertEqual(len(rows), tpm.MAX_ROWS)
        species_types = tpm.load_species_types()
        for i, row in enumerate(rows):
            expected = self.EXPECTED_SPECIES[i]
            self.assertIsNotNone(row, f"row {i} ({expected}) unexpectedly empty")
            result = tpm.identify_row_types(row)
            candidates = tpm.narrow_species_by_types(
                result["identified_types"], result["num_badges_found"], species_types)
            self.assertIn(
                expected, [c.lower() for c in candidates],
                f"row {i}: expected '{expected}' in candidate list, got {candidates} "
                f"(identified_types={result['identified_types']}, "
                f"num_badges_found={result['num_badges_found']})")


@unittest.skipUnless(
    os.path.isdir(TEMPLATES_DIR), "type-badge templates not present in this checkout")
@unittest.skipUnless(
    os.path.exists(SPECIES_TYPES_PATH), "species_types.json not present in this checkout")
@unittest.skipUnless(os.path.exists(VOD_PATH), "jobs/8c10092ac4a9/vod.mp4 not present in this checkout")
class TestRealFootageMultiFrameAggregation(unittest.TestCase):
    """Re-derives 7 real frames of the SAME static team-preview screen (job
    8c10092ac4a9 match 1, t=68/69/70/70.5/71/72/73s - the same frames used
    to find and fix the frame-sensitivity issue documented in the module
    docstring) and runs identify_row_types_multi_frame() over them.

    Real measured result on this exact set of frames, AFTER the
    _refine_oversized_badge_crop() fix landed (2026-07-06): a full, exact
    6/6 - every one of the 6 real rows, including Kingambit's dark+steel
    pair, which previously did NOT reach a full match under aggregation
    alone (its steel badge was classified in only 1 of 7 frames pre-fix,
    below the majority threshold - a per-badge read failure that voting
    alone couldn't fix, which is exactly why the crop-refinement fix was
    pursued as a second, complementary lever - see module docstring).
    This test asserts the safety property strictly (species always a
    candidate) and asserts a conservative floor (>=5/6 full-exact) for the
    aggregation+refinement combination rather than the exact measured 6/6,
    since frame decoding can vary slightly across ffmpeg versions/
    environments - the floor still catches a real regression in either
    fix without being brittle about exact pixel-level reproducibility."""

    EXPECTED_SPECIES = [
        "delphox", "sneasler", "incineroar", "kingambit", "blastoise", "sinistcha",
    ]
    TIMESTAMPS = [68, 69, 70, 70.5, 71, 72, 73]

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, ROOT)
        import analyze_matches as am  # noqa: E402
        cls.am = am
        cls.tmpdir = os.path.join(os.path.dirname(__file__), "_tmp_type_matcher_multiframe_test")
        os.makedirs(cls.tmpdir, exist_ok=True)
        ffmpeg = am.find_ffmpeg()
        cls.columns = []
        for ts in cls.TIMESTAMPS:
            raw_frame = os.path.join(cls.tmpdir, f"frame_raw_{ts}.png")
            subprocess.run(
                [ffmpeg, "-y", "-ss", str(ts), "-i", VOD_PATH, "-frames:v", "1", raw_frame],
                check=True, capture_output=True)
            img = cv2.imread(raw_frame)
            h, w = img.shape[:2]
            scale = am.ROSTER_SCALE_W / w
            resized = cv2.resize(img, (am.ROSTER_SCALE_W, int(round(h * scale))),
                                  interpolation=cv2.INTER_AREA)
            frame_path = os.path.join(cls.tmpdir, f"frame_{ts}.png")
            cv2.imwrite(frame_path, resized)
            column_paths = am.crop_opponent_badge_column([(frame_path, float(ts))])
            if column_paths:
                cls.columns.append(cv2.imread(column_paths[0]))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_aggregation_holds_safety_property_and_improves_on_single_frame(self):
        self.assertGreaterEqual(len(self.columns), 4,
                                 "expected most of the 7 real frames to yield a usable badge column")
        rows_per_frame = [tpm.slice_badge_rows(col) for col in self.columns]
        species_types = tpm.load_species_types()

        full_exact_count = 0
        for i, expected in enumerate(self.EXPECTED_SPECIES):
            row_crops = [rows[i] for rows in rows_per_frame]
            agg = tpm.identify_row_types_multi_frame(row_crops)
            candidates = tpm.narrow_species_by_types(
                agg["identified_types"], agg["num_badges_found"], species_types)
            self.assertIn(
                expected, [c.lower() for c in candidates],
                f"row {i}: expected '{expected}' in candidate list, got {candidates} "
                f"(agg={agg})")
            real_types = set(species_types.get(expected, []))
            if set(agg["identified_types"]) == real_types and agg["num_badges_found"] == len(real_types):
                full_exact_count += 1

        self.assertGreaterEqual(
            full_exact_count, 5,
            f"expected multi-frame aggregation + crop refinement to fully identify at "
            f"least 5/6 rows (measured 6/6 on 2026-07-06), got {full_exact_count}/6")


if __name__ == "__main__":
    unittest.main()
