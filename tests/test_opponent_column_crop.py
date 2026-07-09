"""
Regression tests for analyze_matches.py's opponent-icon-column crop
(crop_opponent_icon_column), added to read_roster()'s image set.

Grounded in a real, visually-confirmed root cause: team-preview frames show
the PLAYER's team with full name text, but the OPPONENT's team as a column
of icons only, with zero text at all (confirmed by inspecting surviving
structure_frames near two real matches' team-preview windows in job
303d13ba0940 - match 2 @620s and match 22 @11050s). That's the actual reason
the roster read misses opponent species at scale (572 roster_conflict events
across 28/30 matches in that job) - not a vision failure so much as a "there
was nothing to read" problem for that half of the frame. This crop hands the
model an EXTRA, zoomed-in view of just that column, alongside (never instead
of) the original full frames.

A LIVE test against real Gemini + real footage (tools_compare_crop_fix.py,
run by the user) then found the first version of this feature could make
things WORSE: on match 4 (the Kingambit case), most of the pre-match sampling
window isn't the team-preview screen at all (crowd shots, black transition
frames), and cropping/zooming those anyway fed the model 4 noise images
alongside only 2 useful ones - which apparently confused it into abandoning a
full-frame read that had been correct without this feature. The fix is
_looks_like_roster_panel: a cheap, free, local color-heuristic filter, since
the roster panel's magenta/maroon background measured ~45-51% coverage on
real confirmed-good crops from that same test, vs. <4% on the crowd crop and
0% on the black crop. These tests cover that filter directly.

Run: py -m unittest tests.test_opponent_column_crop -v   (from poc-starter/)
"""

import os
import tempfile
import unittest

from PIL import Image

import analyze_matches as am

# Falls within analyze_matches._ROSTER_PANEL_HUE_RANGE (300-350 deg) at
# sat=0.87, val=0.59 - comfortably past the min_sat=0.25/min_val=0.15
# thresholds, so a frame filled with this color reads as "looks like the
# roster panel" the same way a real screenshot's magenta row background does.
_PANEL_COLOR = (150, 20, 90)
_NOISE_COLOR = (20, 20, 30)   # a plain dark blue-gray - well outside the hue range


def _make_frame(path, w=1024, h=576, color=_PANEL_COLOR):
    """A plain solid-color stand-in for a real team-preview frame - these
    tests only care about crop geometry/filtering/file handling, not actual
    Pokemon recognition (that requires a live, paid Gemini call, which is
    what tools_compare_crop_fix.py is for). Defaults to the roster-panel
    color so tests that just want "a crop gets produced" don't also have to
    think about the filter; tests of the filter itself pass color=_NOISE_COLOR
    explicitly."""
    Image.new("RGB", (w, h), color=color).save(path)


class TestCropOpponentIconColumn(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_empty_list_returns_empty_list(self):
        self.assertEqual(am.crop_opponent_icon_column([]), [])

    def test_produces_one_cropped_file_per_frame(self):
        paths = []
        for i in range(3):
            p = os.path.join(self.tmp.name, f"prev0_{i:05d}.jpg")
            _make_frame(p)
            paths.append((p, float(i)))
        out = am.crop_opponent_icon_column(paths)
        self.assertEqual(len(out), 3)
        for p in out:
            self.assertTrue(os.path.exists(p))
            self.assertTrue(p.endswith("_oppcol.png"))

    def test_cropped_output_matches_box_and_zoom_dimensions(self):
        p = os.path.join(self.tmp.name, "prev0_00000.jpg")
        _make_frame(p, w=1024, h=576)
        out = am.crop_opponent_icon_column([(p, 0.0)])
        self.assertEqual(len(out), 1)
        left, top, right, bottom = am.OPPONENT_COLUMN_BOX
        expected_w = (int(1024 * right) - int(1024 * left)) * am.OPPONENT_COLUMN_ZOOM
        expected_h = (int(576 * bottom) - int(576 * top)) * am.OPPONENT_COLUMN_ZOOM
        with Image.open(out[0]) as im:
            self.assertEqual(im.size, (expected_w, expected_h))

    def test_box_stays_within_right_side_of_frame(self):
        """The whole point of this crop is the opponent's column specifically -
        it must not accidentally include most of the player's (left) side."""
        left, top, right, bottom = am.OPPONENT_COLUMN_BOX
        self.assertGreaterEqual(left, 0.5)
        self.assertLessEqual(right, 1.0)
        self.assertLess(top, bottom)

    def test_unreadable_frame_is_skipped_not_raised(self):
        bad_path = os.path.join(self.tmp.name, "not_an_image.jpg")
        with open(bad_path, "w") as f:
            f.write("not a real jpeg")
        good_path = os.path.join(self.tmp.name, "prev0_00000.jpg")
        _make_frame(good_path)
        out = am.crop_opponent_icon_column([(bad_path, 0.0), (good_path, 1.0)])
        # bad frame silently skipped, good frame still produced
        self.assertEqual(len(out), 1)

    def test_missing_file_is_skipped_not_raised(self):
        out = am.crop_opponent_icon_column([("/no/such/file.jpg", 0.0)])
        self.assertEqual(out, [])

    def test_custom_box_and_zoom_are_respected(self):
        p = os.path.join(self.tmp.name, "prev0_00000.jpg")
        _make_frame(p, w=1000, h=500)
        out = am.crop_opponent_icon_column([(p, 0.0)], box=(0.5, 0.0, 1.0, 1.0), zoom=2)
        with Image.open(out[0]) as im:
            self.assertEqual(im.size, (500 * 2, 500 * 2))

    def test_noise_frames_are_filtered_out_entirely(self):
        """The exact bug found by the live A/B test: crowd-scene/black-screen
        frames from the pre-match window must NOT produce a crop at all, not
        just a low-quality one - they were actively harmful when included."""
        paths = []
        for i in range(4):
            p = os.path.join(self.tmp.name, f"prev0_{i:05d}.jpg")
            _make_frame(p, color=_NOISE_COLOR)
            paths.append((p, float(i)))
        out = am.crop_opponent_icon_column(paths)
        self.assertEqual(out, [])

    def test_mixed_noise_and_panel_frames_only_keeps_panel_ones(self):
        """Mirrors match 4's real result: 4 noise frames + 2 real roster-panel
        frames should yield exactly 2 crops, not 6."""
        paths = []
        for i in range(4):
            p = os.path.join(self.tmp.name, f"noise_{i:05d}.jpg")
            _make_frame(p, color=_NOISE_COLOR)
            paths.append((p, float(i)))
        for i in range(2):
            p = os.path.join(self.tmp.name, f"panel_{i:05d}.jpg")
            _make_frame(p, color=_PANEL_COLOR)
            paths.append((p, float(i + 4)))
        out = am.crop_opponent_icon_column(paths)
        self.assertEqual(len(out), 2)
        for p in out:
            self.assertIn("panel_", p)

    def test_max_output_cap_is_respected_even_with_more_good_frames(self):
        paths = []
        for i in range(10):
            p = os.path.join(self.tmp.name, f"prev0_{i:05d}.jpg")
            _make_frame(p, color=_PANEL_COLOR)
            paths.append((p, float(i)))
        out = am.crop_opponent_icon_column(paths, max_output=3)
        self.assertEqual(len(out), 3)

    def test_scans_past_leading_noise_to_find_good_frames_later(self):
        """The real bug wasn't just noise dilution - the old code also only
        ever looked at a fixed head-slice of the sampled frames. This checks
        the fix: good frames near the END of a long list must still be found."""
        paths = []
        for i in range(8):
            p = os.path.join(self.tmp.name, f"noise_{i:05d}.jpg")
            _make_frame(p, color=_NOISE_COLOR)
            paths.append((p, float(i)))
        p_good = os.path.join(self.tmp.name, "panel_00000.jpg")
        _make_frame(p_good, color=_PANEL_COLOR)
        paths.append((p_good, 8.0))
        out = am.crop_opponent_icon_column(paths)
        self.assertEqual(len(out), 1)


class TestLooksLikeRosterPanel(unittest.TestCase):

    def test_panel_colored_image_passes(self):
        im = Image.new("RGB", (100, 200), color=_PANEL_COLOR)
        self.assertTrue(am._looks_like_roster_panel(im))

    def test_noise_colored_image_fails(self):
        im = Image.new("RGB", (100, 200), color=_NOISE_COLOR)
        self.assertFalse(am._looks_like_roster_panel(im))

    def test_black_image_fails(self):
        im = Image.new("RGB", (100, 200), color=(0, 0, 0))
        self.assertFalse(am._looks_like_roster_panel(im))

    def test_mostly_noise_with_small_panel_patch_fails_below_threshold(self):
        """A small sliver of panel color amid mostly-noise shouldn't pass -
        the threshold requires a real, substantial fraction, not just any."""
        im = Image.new("RGB", (100, 100), color=_NOISE_COLOR)
        patch = Image.new("RGB", (5, 5), color=_PANEL_COLOR)
        im.paste(patch, (0, 0))
        self.assertFalse(am._looks_like_roster_panel(im))


class TestBuildRosterPromptMentionsCrop(unittest.TestCase):

    def test_doubles_prompt_explains_supplementary_crops(self):
        prompt = am.build_roster_prompt({"bring_count": 4, "team_size": 6})
        self.assertIn("opponent's", prompt)
        self.assertIn("icon-only team column", prompt)

    def test_singles_prompt_also_explains_supplementary_crops(self):
        prompt = am.build_roster_prompt({"bring_count": None, "team_size": 6})
        self.assertIn("icon-only team column", prompt)

    def test_prompt_tells_model_to_use_type_badges_as_a_disambiguator(self):
        """Added after a live test showed the crop DID zoom in on the right
        icon (a Dark+Steel row - Kingambit/Bisharp's exact typing, visually
        confirmed by viewing the real crop from job 303d13ba0940 match 4), but
        the model still guessed unrelated species (Scizor, Weavile, Drednaw)
        for that slot across repeated live calls - it wasn't being told the
        type badges next to each icon are themselves a strong identification
        signal, not just decoration."""
        prompt = am.build_roster_prompt({"bring_count": 4, "team_size": 6})
        self.assertIn("type badge", prompt.lower())


if __name__ == "__main__":
    unittest.main()
