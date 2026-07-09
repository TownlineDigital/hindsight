"""
Tests for analyze_matches.attach_opponent_type_hints and its wiring into
read_roster() (task #171/#189).

This is the "flag, don't force a guess" wiring decision for
accuracy_addons/team_preview_type_matcher.py: that module's own HONEST
CURRENT SCOPE docstring reports a strong candidate-list-recall result
(42/42 correct on real footage) but validated against only ONE real match
so far, with full both-badge accuracy still frame-sensitive - not yet
trusted enough to auto-correct opponent_team the way
apply_likely_missed_species_correction does for roster-conflict flags.
So read_roster() now runs it as a purely ADDITIVE, supplementary signal
(roster["opponent_row_type_hints"]) using the SAME crop_opponent_badge_
column() frames already sampled for the roster read - zero extra Gemini
calls, exactly like crop_opponent_icon_column already added to the same
call for free.

These tests cover the WIRING (does read_roster call
crop_opponent_badge_column and pass results through to
attach_opponent_type_hints; does attach_opponent_type_hints correctly
combine frames across attempts, filter to ALLOWED_SPECIES, and stay a
no-op when there's nothing to add) with team_preview_type_matcher's own
pixel-level functions mocked out - the pixel-level mechanics themselves are
already covered by tests/test_team_preview_type_matcher.py.

Run: py -m unittest tests.test_opponent_type_hints -v   (from poc-starter/)
"""

import subprocess
import unittest
from unittest.mock import patch, MagicMock

import cv2

import analyze_matches as am
from accuracy_addons import team_preview_type_matcher as tptm


class TestAttachOpponentTypeHints(unittest.TestCase):

    def test_noop_when_no_badge_paths_at_all(self):
        roster = {"player_team": ["A"], "opponent_team": ["B"]}
        out = am.attach_opponent_type_hints(roster, [[], []])
        self.assertEqual(out, roster)
        self.assertNotIn("opponent_row_type_hints", out)

    def test_noop_when_every_crop_is_unreadable(self):
        with patch.object(cv2, "imread", return_value=None):
            roster = {}
            am.attach_opponent_type_hints(roster, [["bad1.png"], ["bad2.png"]])
        self.assertNotIn("opponent_row_type_hints", roster)

    def test_noop_when_no_row_gets_any_identified_type(self):
        with patch.object(cv2, "imread", return_value="fake_img"), \
             patch.object(tptm, "slice_badge_rows", return_value=["row0", None, None, None, None, None]), \
             patch.object(tptm, "identify_row_types_multi_frame",
                          return_value={"num_badges_found": 0, "identified_types": [],
                                        "n_frames_used": 1, "type_votes": {}, "badge_count_votes": {}}):
            roster = {}
            am.attach_opponent_type_hints(roster, [["frame_a.png"]])
        self.assertNotIn("opponent_row_type_hints", roster)

    def test_attaches_hints_for_rows_with_identified_types(self):
        def fake_slice(img, max_rows=6):
            # row 0 has content, rest are empty slots
            return ["row0"] + [None] * (max_rows - 1)

        fake_result = {"num_badges_found": 2, "identified_types": ["dark", "steel"],
                       "n_frames_used": 3, "type_votes": {"dark": 3, "steel": 3},
                       "badge_count_votes": {2: 3}}

        with patch.object(cv2, "imread", return_value="fake_img"), \
             patch.object(tptm, "slice_badge_rows", side_effect=fake_slice), \
             patch.object(tptm, "identify_row_types_multi_frame", return_value=fake_result), \
             patch.object(tptm, "narrow_species_by_types", return_value=["kingambit"]):
            roster = {"opponent_team": ["Kingambit"]}
            am.attach_opponent_type_hints(roster, [["a.png", "b.png"], ["c.png"]])

        self.assertIn("opponent_row_type_hints", roster)
        hints = roster["opponent_row_type_hints"]
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]["row"], 0)
        self.assertEqual(hints[0]["identified_types"], ["dark", "steel"])
        self.assertEqual(hints[0]["num_badges_found"], 2)
        self.assertEqual(hints[0]["candidate_species"], ["kingambit"])

    def test_color_check_defaults_to_on_and_is_forwarded_to_multi_frame(self):
        """2026-07-08: use_color_check defaults to True in production (the
        user's own request - "I think it will improve accuracy at scale") -
        confirms attach_opponent_type_hints actually forwards that default
        through to identify_row_types_multi_frame's own use_color_check
        parameter, rather than silently dropping it."""
        captured = {}

        def fake_multi_frame(row_crops, min_score=tptm.MIN_BADGE_MATCH_SCORE,
                              min_frame_agreement=None, use_color_check=False):
            captured["use_color_check"] = use_color_check
            return {"num_badges_found": 0, "identified_types": [], "n_frames_used": 1,
                    "type_votes": {}, "badge_count_votes": {}}

        with patch.object(cv2, "imread", return_value="fake_img"), \
             patch.object(tptm, "slice_badge_rows", return_value=["row0"] + [None] * 5), \
             patch.object(tptm, "identify_row_types_multi_frame", side_effect=fake_multi_frame):
            am.attach_opponent_type_hints({}, [["a.png"]])

        self.assertTrue(captured["use_color_check"])

    def test_color_check_can_still_be_disabled_explicitly(self):
        captured = {}

        def fake_multi_frame(row_crops, min_score=tptm.MIN_BADGE_MATCH_SCORE,
                              min_frame_agreement=None, use_color_check=False):
            captured["use_color_check"] = use_color_check
            return {"num_badges_found": 0, "identified_types": [], "n_frames_used": 1,
                    "type_votes": {}, "badge_count_votes": {}}

        with patch.object(cv2, "imread", return_value="fake_img"), \
             patch.object(tptm, "slice_badge_rows", return_value=["row0"] + [None] * 5), \
             patch.object(tptm, "identify_row_types_multi_frame", side_effect=fake_multi_frame):
            am.attach_opponent_type_hints({}, [["a.png"]], use_color_check=False)

        self.assertFalse(captured["use_color_check"])

    def test_pools_frames_across_all_attempts_before_slicing(self):
        """badge_paths_by_attempt has 2 inner lists (one per ROSTER_SEARCH_ATTEMPTS
        window) - every path from BOTH should be sliced and handed to
        identify_row_types_multi_frame together, not just the first attempt's."""
        seen_paths = []

        def fake_imread(path):
            seen_paths.append(path)
            return "fake_img"

        with patch.object(cv2, "imread", side_effect=fake_imread), \
             patch.object(tptm, "slice_badge_rows", return_value=["row0"] + [None] * 5), \
             patch.object(tptm, "identify_row_types_multi_frame",
                          return_value={"num_badges_found": 0, "identified_types": [],
                                        "n_frames_used": 0, "type_votes": {}, "badge_count_votes": {}}):
            am.attach_opponent_type_hints({}, [["attempt1_a.png", "attempt1_b.png"], ["attempt2_a.png"]])

        self.assertEqual(sorted(seen_paths), ["attempt1_a.png", "attempt1_b.png", "attempt2_a.png"])

    def test_species_map_passed_to_narrowing_is_restricted_to_allowed_species(self):
        """The narrowing search should only consider species legal in the
        CURRENTLY CONFIGURED regulation (ALLOWED_SPECIES), not the full
        212-species data file - a tighter, more relevant candidate list."""
        captured = {}

        def fake_narrow(identified_types, num_badges_found, candidate_species_types=None):
            captured["species_map"] = candidate_species_types
            return []

        fake_species_types = {"kingambit": ["dark", "steel"], "not-a-legal-species": ["fire"]}

        with patch.object(am, "ALLOWED_SPECIES", {"kingambit"}), \
             patch.object(cv2, "imread", return_value="fake_img"), \
             patch.object(tptm, "slice_badge_rows", return_value=["row0"] + [None] * 5), \
             patch.object(tptm, "load_species_types", return_value=fake_species_types), \
             patch.object(tptm, "identify_row_types_multi_frame",
                          return_value={"num_badges_found": 1, "identified_types": ["dark"],
                                        "n_frames_used": 1, "type_votes": {}, "badge_count_votes": {}}), \
             patch.object(tptm, "narrow_species_by_types", side_effect=fake_narrow):
            am.attach_opponent_type_hints({}, [["a.png"]])

        self.assertEqual(captured["species_map"], {"kingambit": ["dark", "steel"]})

    def test_mutates_and_returns_the_same_roster_dict(self):
        roster = {}
        out = am.attach_opponent_type_hints(roster, [])
        self.assertIs(out, roster)

    def test_row_top_and_height_frac_forwarded_to_slice_badge_rows(self):
        """task #206: attach_opponent_type_hints must forward its own
        row_top_frac/row_height_frac kwargs through to slice_badge_rows -
        this is how a landscape video's corrected row geometry (see
        analyze_matches.badge_column_geometry) actually reaches the
        pixel-level slicing, not just get silently dropped."""
        captured = {}

        def fake_slice(img, max_rows=6, **kw):
            captured.update(kw)
            return ["row0"] + [None] * (max_rows - 1)

        with patch.object(cv2, "imread", return_value="fake_img"), \
             patch.object(tptm, "slice_badge_rows", side_effect=fake_slice), \
             patch.object(tptm, "identify_row_types_multi_frame",
                          return_value={"num_badges_found": 0, "identified_types": [],
                                        "n_frames_used": 1, "type_votes": {}, "badge_count_votes": {}}):
            am.attach_opponent_type_hints({}, [["a.png"]], row_top_frac=0.0, row_height_frac=1 / 6)

        self.assertEqual(captured, {"row_top_frac": 0.0, "row_height_frac": 1 / 6})

    def test_default_none_row_fracs_are_not_forwarded_at_all(self):
        """Leaving row_top_frac/row_height_frac unset (None, the default)
        must NOT pass those kwargs to slice_badge_rows at all - so existing
        callers (and slice_badge_rows' own defaults, tuned for portrait
        video) are completely unaffected, per badge_column_geometry's own
        docstring on None's meaning."""
        captured = {"called_with_kwargs": None}

        def fake_slice(img, max_rows=6, **kw):
            captured["called_with_kwargs"] = kw
            return ["row0"] + [None] * (max_rows - 1)

        with patch.object(cv2, "imread", return_value="fake_img"), \
             patch.object(tptm, "slice_badge_rows", side_effect=fake_slice), \
             patch.object(tptm, "identify_row_types_multi_frame",
                          return_value={"num_badges_found": 0, "identified_types": [],
                                        "n_frames_used": 1, "type_votes": {}, "badge_count_votes": {}}):
            am.attach_opponent_type_hints({}, [["a.png"]])

        self.assertEqual(captured["called_with_kwargs"], {})


class TestDetectVideoDimensions(unittest.TestCase):
    """Tests for analyze_matches.detect_video_dimensions (task #206) - a
    single ffmpeg probe call exposing BOTH width and height (previously only
    width was exposed via detect_video_width), so a video's orientation
    (portrait vs landscape) can be determined - see
    badge_column_geometry's own docstring for why that matters."""

    def _run_with_stderr(self, stderr_text):
        fake_result = MagicMock()
        fake_result.stderr = stderr_text
        with patch.object(subprocess, "run", return_value=fake_result):
            return am.detect_video_dimensions("ffmpeg", "video.mp4")

    def test_parses_landscape_dimensions_from_ffmpeg_stderr(self):
        stderr = ("Stream #0:0: Video: h264 (High), yuv420p, 1280x720 [SAR 1:1 DAR 16:9], "
                   "30 fps, 30 tbr, 1200k tbn")
        self.assertEqual(self._run_with_stderr(stderr), (1280, 720))

    def test_parses_portrait_dimensions_from_ffmpeg_stderr(self):
        stderr = "Stream #0:0: Video: h264 (Main), yuv420p, 1290x2796, 30 fps"
        self.assertEqual(self._run_with_stderr(stderr), (1290, 2796))

    def test_returns_none_none_when_no_video_stream_line_matches(self):
        self.assertEqual(self._run_with_stderr("no video stream info here at all"), (None, None))

    def test_returns_none_none_on_subprocess_exception(self):
        with patch.object(subprocess, "run", side_effect=OSError("ffmpeg not found")):
            self.assertEqual(am.detect_video_dimensions("ffmpeg", "video.mp4"), (None, None))

    def test_returns_none_none_on_timeout(self):
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("ffmpeg", 15)):
            self.assertEqual(am.detect_video_dimensions("ffmpeg", "video.mp4"), (None, None))

    def test_detect_video_width_delegates_to_dimensions(self):
        with patch.object(am, "detect_video_dimensions", return_value=(1280, 720)) as mock_dims:
            width = am.detect_video_width("ffmpeg", "video.mp4")
        self.assertEqual(width, 1280)
        mock_dims.assert_called_once_with("ffmpeg", "video.mp4")

    def test_detect_video_width_returns_none_when_dimensions_unknown(self):
        with patch.object(am, "detect_video_dimensions", return_value=(None, None)):
            self.assertIsNone(am.detect_video_width("ffmpeg", "video.mp4"))


class TestBadgeColumnGeometry(unittest.TestCase):
    """Tests for analyze_matches.badge_column_geometry (task #206) - see its
    own docstring, and LANDSCAPE_OPPONENT_BADGE_COLUMN_BOX's comment, for
    the real, measured bug this selector fixes: the original portrait-tuned
    OPPONENT_BADGE_COLUMN_BOX/ROW_TOP_FRAC/ROW_HEIGHT_FRAC produced a 0%
    confident-badge-read rate on a real landscape (1280x720) Twitch VOD."""

    def test_landscape_dimensions_return_landscape_constants(self):
        box, row_top, row_height = am.badge_column_geometry(1280, 720)
        self.assertEqual(box, am.LANDSCAPE_OPPONENT_BADGE_COLUMN_BOX)
        self.assertEqual(row_top, am.LANDSCAPE_ROW_TOP_FRAC)
        self.assertEqual(row_height, am.LANDSCAPE_ROW_HEIGHT_FRAC)

    def test_portrait_dimensions_return_original_constants_and_none_fracs(self):
        box, row_top, row_height = am.badge_column_geometry(1290, 2796)
        self.assertEqual(box, am.OPPONENT_BADGE_COLUMN_BOX)
        self.assertIsNone(row_top)
        self.assertIsNone(row_height)

    def test_square_dimensions_are_not_treated_as_landscape(self):
        """width > height specifically, not just 'not portrait' - an
        unusual square video should get the conservative, already-validated
        portrait default rather than an unproven landscape guess."""
        box, row_top, row_height = am.badge_column_geometry(1000, 1000)
        self.assertEqual(box, am.OPPONENT_BADGE_COLUMN_BOX)
        self.assertIsNone(row_top)
        self.assertIsNone(row_height)

    def test_unknown_dimensions_fall_back_to_portrait_defaults(self):
        box, row_top, row_height = am.badge_column_geometry(None, None)
        self.assertEqual(box, am.OPPONENT_BADGE_COLUMN_BOX)
        self.assertIsNone(row_top)
        self.assertIsNone(row_height)

    def test_zero_dimensions_fall_back_to_portrait_defaults(self):
        """0 is falsy - treated the same as None (probe technically
        'succeeded' but returned a nonsensical value), not as a valid
        width/height to compare."""
        box, row_top, row_height = am.badge_column_geometry(0, 0)
        self.assertEqual(box, am.OPPONENT_BADGE_COLUMN_BOX)
        self.assertIsNone(row_top)
        self.assertIsNone(row_height)


class TestReadRosterWiresInTypeHints(unittest.TestCase):
    """read_roster() should collect crop_opponent_badge_column() output for
    every attempt (reusing the SAME already-sampled frames as the roster
    read itself - zero extra Gemini calls) and pass all of it through to
    attach_opponent_type_hints on the final merged roster."""

    def _run(self, attempt_results):
        def fake_sample_window(*a, **kw):
            return [("fake_frame.jpg", 0.0)]

        def fake_crop_icon(*a, **kw):
            return []

        calls = {"n": 0}

        def fake_call_with_fallback(client, hard, cheap, prompt, paths):
            i = calls["n"]
            calls["n"] += 1
            return attempt_results[i]

        with patch.object(am, "sample_window", fake_sample_window), \
             patch.object(am, "crop_opponent_icon_column", fake_crop_icon), \
             patch.object(am, "call_with_fallback", fake_call_with_fallback), \
             patch.object(am, "crop_opponent_badge_column") as mock_badge_crop, \
             patch.object(am, "attach_opponent_type_hints") as mock_attach:
            mock_badge_crop.side_effect = lambda capped: [f"badge_for_{capped[0][0]}"]
            roster, had_failure = am.read_roster(
                None, "model", "model", "ffmpeg", "video.mp4", 100, "workdir", "")
            return roster, had_failure, mock_badge_crop, mock_attach

    def test_badge_column_crop_called_once_per_attempt(self):
        results = [{"player_team": ["A"], "opponent_team": ["X"]}] * len(am.ROSTER_SEARCH_ATTEMPTS)
        _roster, _had_failure, mock_badge_crop, _mock_attach = self._run(results)
        self.assertEqual(mock_badge_crop.call_count, len(am.ROSTER_SEARCH_ATTEMPTS))

    def test_attach_opponent_type_hints_called_with_merged_roster_and_all_badge_paths(self):
        results = [{"player_team": ["A"], "opponent_team": ["X"]}] * len(am.ROSTER_SEARCH_ATTEMPTS)
        roster, _had_failure, _mock_badge_crop, mock_attach = self._run(results)
        mock_attach.assert_called_once()
        called_roster, called_badge_paths = mock_attach.call_args[0]
        self.assertIs(called_roster, roster)
        self.assertEqual(len(called_badge_paths), len(am.ROSTER_SEARCH_ATTEMPTS))

    def test_badge_crop_failure_does_not_break_the_roster_read(self):
        """crop_opponent_badge_column raising must not take down the whole
        roster read - the roster itself (from Gemini) is far more important
        than this purely-supplementary local signal."""
        def fake_sample_window(*a, **kw):
            return [("fake_frame.jpg", 0.0)]

        def fake_crop_icon(*a, **kw):
            return []

        good = {"player_team": ["A", "B"], "opponent_team": ["X", "Y"]}

        def fake_call(client, hard, cheap, prompt, paths):
            return good

        with patch.object(am, "sample_window", fake_sample_window), \
             patch.object(am, "crop_opponent_icon_column", fake_crop_icon), \
             patch.object(am, "call_with_fallback", fake_call), \
             patch.object(am, "crop_opponent_badge_column", side_effect=RuntimeError("boom")):
            roster, had_failure = am.read_roster(
                None, "model", "model", "ffmpeg", "video.mp4", 100, "workdir", "")
        self.assertEqual(roster["player_team"], ["A", "B"])
        self.assertFalse(had_failure)

    def test_no_frames_at_all_never_calls_badge_crop_or_attach(self):
        def fake_sample_window(*a, **kw):
            return []

        with patch.object(am, "sample_window", fake_sample_window), \
             patch.object(am, "crop_opponent_badge_column") as mock_badge_crop, \
             patch.object(am, "attach_opponent_type_hints") as mock_attach:
            roster, had_failure = am.read_roster(
                None, "model", "model", "ffmpeg", "video.mp4", 100, "workdir", "")
        self.assertEqual(roster, {})
        mock_badge_crop.assert_not_called()
        mock_attach.assert_not_called()

    def test_landscape_video_geometry_reaches_badge_crop_and_attach_hints(self):
        """task #206 end-to-end wiring: on a detected-landscape video,
        read_roster must pass LANDSCAPE_OPPONENT_BADGE_COLUMN_BOX as the
        crop_opponent_badge_column box= kwarg, and the landscape row_top_
        frac/row_height_frac through to attach_opponent_type_hints - not
        silently keep using the portrait defaults."""
        def fake_sample_window(*a, **kw):
            return [("fake_frame.jpg", 0.0)]

        def fake_crop_icon(*a, **kw):
            return []

        good = {"player_team": ["A"], "opponent_team": ["X"]}

        def fake_call(client, hard, cheap, prompt, paths):
            return good

        with patch.object(am, "sample_window", fake_sample_window), \
             patch.object(am, "crop_opponent_icon_column", fake_crop_icon), \
             patch.object(am, "call_with_fallback", fake_call), \
             patch.object(am, "detect_video_dimensions", return_value=(1280, 720)), \
             patch.object(am, "crop_opponent_badge_column", return_value=[]) as mock_badge_crop, \
             patch.object(am, "attach_opponent_type_hints") as mock_attach:
            am.read_roster(None, "model", "model", "ffmpeg", "video.mp4", 100, "workdir", "")

        for call in mock_badge_crop.call_args_list:
            self.assertEqual(call.kwargs.get("box"), am.LANDSCAPE_OPPONENT_BADGE_COLUMN_BOX)
        mock_attach.assert_called_once()
        _called_roster, _called_paths = mock_attach.call_args[0]
        self.assertEqual(mock_attach.call_args.kwargs.get("row_top_frac"), am.LANDSCAPE_ROW_TOP_FRAC)
        self.assertEqual(mock_attach.call_args.kwargs.get("row_height_frac"), am.LANDSCAPE_ROW_HEIGHT_FRAC)

    def test_portrait_or_unknown_video_geometry_uses_original_defaults(self):
        """When dimensions are unknown (probe failure), read_roster must
        fall back to the ORIGINAL OPPONENT_BADGE_COLUMN_BOX and pass no
        row_top_frac/row_height_frac override at all (None, None) - the
        conservative, already-validated default, not a guess."""
        def fake_sample_window(*a, **kw):
            return [("fake_frame.jpg", 0.0)]

        def fake_crop_icon(*a, **kw):
            return []

        good = {"player_team": ["A"], "opponent_team": ["X"]}

        def fake_call(client, hard, cheap, prompt, paths):
            return good

        with patch.object(am, "sample_window", fake_sample_window), \
             patch.object(am, "crop_opponent_icon_column", fake_crop_icon), \
             patch.object(am, "call_with_fallback", fake_call), \
             patch.object(am, "detect_video_dimensions", return_value=(None, None)), \
             patch.object(am, "crop_opponent_badge_column", return_value=[]) as mock_badge_crop, \
             patch.object(am, "attach_opponent_type_hints") as mock_attach:
            am.read_roster(None, "model", "model", "ffmpeg", "video.mp4", 100, "workdir", "")

        for call in mock_badge_crop.call_args_list:
            self.assertEqual(call.kwargs.get("box"), am.OPPONENT_BADGE_COLUMN_BOX)
        mock_attach.assert_called_once()
        self.assertIsNone(mock_attach.call_args.kwargs.get("row_top_frac"))
        self.assertIsNone(mock_attach.call_args.kwargs.get("row_height_frac"))


class TestApplyTypeBadgeOverride(unittest.TestCase):
    """Tests for analyze_matches.apply_type_badge_override (task #204) - the
    real, found case: match 1 of the 2026-07-08 Twitch VOD run had a row
    showing an unmistakable Kingambit icon (dark bipedal body, gold blade)
    next to two clean Dark+Steel badges - Kingambit is the ONLY Dark/Steel
    dual-type in this format's legal pool - but Gemini's own roster read
    called that row "Heracross" anyway. The user visually confirmed the
    badges were right and asked for this exact case to override the guess
    rather than just flag it (unlike attach_opponent_type_hints, which stays
    informational-only in the general case)."""

    def test_noop_when_no_hints_at_all(self):
        roster = {"opponent_team": ["Heracross", "Garchomp"]}
        out = am.apply_type_badge_override(roster)
        self.assertIs(out, roster)
        self.assertNotIn("type_badge_overrides", out)
        self.assertEqual(out["opponent_team"], ["Heracross", "Garchomp"])

    def test_noop_when_opponent_team_missing_or_not_a_list(self):
        roster = {"opponent_row_type_hints": [{"row": 0, "candidate_species": ["Kingambit"],
                                                "num_badges_found": 2}]}
        out = am.apply_type_badge_override(roster)
        self.assertNotIn("type_badge_overrides", out)

    def test_overrides_unique_candidate_with_both_badges_found(self):
        roster = {
            "opponent_team": ["Sylveon", "Garchomp", "Aerodactyl", "Heracross", "Girafarig", "Charizard"],
            "opponent_row_type_hints": [
                {"row": 3, "identified_types": ["dark", "steel"], "num_badges_found": 2,
                 "candidate_species": ["Kingambit"]},
            ],
        }
        out = am.apply_type_badge_override(roster)
        self.assertEqual(out["opponent_team"][3], "Kingambit")
        self.assertEqual(out["type_badge_overrides"],
                         [{"row": 3, "was": "Heracross", "now": "Kingambit",
                           "identified_types": ["dark", "steel"]}])

    def test_does_not_override_when_more_than_one_candidate(self):
        roster = {
            "opponent_team": ["Heracross"],
            "opponent_row_type_hints": [
                {"row": 0, "identified_types": ["dark"], "num_badges_found": 1,
                 "candidate_species": ["Kingambit", "Bisharp"]},
            ],
        }
        out = am.apply_type_badge_override(roster)
        self.assertEqual(out["opponent_team"], ["Heracross"])
        self.assertNotIn("type_badge_overrides", out)

    def test_does_not_override_on_single_badge_partial_match(self):
        """num_badges_found == 1 means only a partial type signal (see
        narrow_species_by_types) - not trusted enough to override even if,
        coincidentally, only one candidate happens to match."""
        roster = {
            "opponent_team": ["Heracross"],
            "opponent_row_type_hints": [
                {"row": 0, "identified_types": ["steel"], "num_badges_found": 1,
                 "candidate_species": ["Kingambit"]},
            ],
        }
        out = am.apply_type_badge_override(roster)
        self.assertEqual(out["opponent_team"], ["Heracross"])
        self.assertNotIn("type_badge_overrides", out)

    def test_does_not_override_when_row_index_out_of_range(self):
        roster = {
            "opponent_team": ["Heracross"],
            "opponent_row_type_hints": [
                {"row": 5, "identified_types": ["dark", "steel"], "num_badges_found": 2,
                 "candidate_species": ["Kingambit"]},
            ],
        }
        out = am.apply_type_badge_override(roster)
        self.assertEqual(out["opponent_team"], ["Heracross"])
        self.assertNotIn("type_badge_overrides", out)

    def test_noop_when_candidate_already_matches_current_name(self):
        roster = {
            "opponent_team": ["Kingambit"],
            "opponent_row_type_hints": [
                {"row": 0, "identified_types": ["dark", "steel"], "num_badges_found": 2,
                 "candidate_species": ["Kingambit"]},
            ],
        }
        out = am.apply_type_badge_override(roster)
        self.assertEqual(out["opponent_team"], ["Kingambit"])
        self.assertNotIn("type_badge_overrides", out)

    def test_does_not_override_when_candidate_already_present_elsewhere(self):
        """Species Clause forbids duplicates - if the unique candidate is
        already present at a DIFFERENT row, this is more likely a row-
        ordering mismatch between the badge column and Gemini's own list
        order than a genuine correction, so this backs off rather than risk
        creating a duplicate or clobbering a row that was actually right."""
        roster = {
            "opponent_team": ["Kingambit", "Heracross"],
            "opponent_row_type_hints": [
                {"row": 1, "identified_types": ["dark", "steel"], "num_badges_found": 2,
                 "candidate_species": ["Kingambit"]},
            ],
        }
        out = am.apply_type_badge_override(roster)
        self.assertEqual(out["opponent_team"], ["Kingambit", "Heracross"])
        self.assertNotIn("type_badge_overrides", out)

    def test_multiple_rows_can_each_override_independently(self):
        roster = {
            "opponent_team": ["Heracross", "Weezing"],
            "opponent_row_type_hints": [
                {"row": 0, "identified_types": ["dark", "steel"], "num_badges_found": 2,
                 "candidate_species": ["Kingambit"]},
                {"row": 1, "identified_types": ["water", "ghost"], "num_badges_found": 2,
                 "candidate_species": ["Basculegion"]},
            ],
        }
        out = am.apply_type_badge_override(roster)
        self.assertEqual(out["opponent_team"], ["Kingambit", "Basculegion"])
        self.assertEqual(len(out["type_badge_overrides"]), 2)

    def test_mutates_and_returns_the_same_roster_dict(self):
        roster = {"opponent_team": ["X"]}
        out = am.apply_type_badge_override(roster)
        self.assertIs(out, roster)


class TestReadRosterWiresInTypeBadgeOverride(unittest.TestCase):
    """read_roster() should call apply_type_badge_override on the merged
    roster right after attach_opponent_type_hints, so an override actually
    reaches opponent_team before read_roster returns (and therefore before
    reject_banned_species/build_event_prompt see it downstream)."""

    def test_apply_type_badge_override_called_after_attach_hints(self):
        def fake_sample_window(*a, **kw):
            return [("fake_frame.jpg", 0.0)]

        def fake_crop_icon(*a, **kw):
            return []

        good = {"player_team": ["A"], "opponent_team": ["Heracross"]}

        def fake_call(client, hard, cheap, prompt, paths):
            return good

        call_order = []

        def fake_attach(roster, badge_paths, **kw):
            call_order.append("attach")
            return roster

        def fake_override(roster):
            call_order.append("override")
            return roster

        with patch.object(am, "sample_window", fake_sample_window), \
             patch.object(am, "crop_opponent_icon_column", fake_crop_icon), \
             patch.object(am, "call_with_fallback", fake_call), \
             patch.object(am, "crop_opponent_badge_column", return_value=[]), \
             patch.object(am, "attach_opponent_type_hints", side_effect=fake_attach), \
             patch.object(am, "apply_type_badge_override", side_effect=fake_override) as mock_override:
            roster, _had_failure = am.read_roster(
                None, "model", "model", "ffmpeg", "video.mp4", 100, "workdir", "")

        mock_override.assert_called_once()
        self.assertEqual(call_order, ["attach", "override"])
        self.assertIs(mock_override.call_args[0][0], roster)

    def test_real_override_reaches_opponent_team_before_read_roster_returns(self):
        """End-to-end (real attach_opponent_type_hints + apply_type_badge_
        override, only the pixel-level team_preview_type_matcher calls
        mocked): a unique Dark+Steel badge read on row 0 should flip
        'Heracross' to 'Kingambit' in the roster read_roster() actually
        returns."""
        def fake_sample_window(*a, **kw):
            return [("fake_frame.jpg", 0.0)]

        def fake_crop_icon(*a, **kw):
            return []

        good = {"player_team": ["A"], "opponent_team": ["Heracross"]}

        def fake_call(client, hard, cheap, prompt, paths):
            return good

        fake_result = {"num_badges_found": 2, "identified_types": ["dark", "steel"],
                       "n_frames_used": 3, "type_votes": {"dark": 3, "steel": 3},
                       "badge_count_votes": {2: 3}}

        with patch.object(am, "sample_window", fake_sample_window), \
             patch.object(am, "crop_opponent_icon_column", fake_crop_icon), \
             patch.object(am, "call_with_fallback", fake_call), \
             patch.object(am, "crop_opponent_badge_column", return_value=["badge.png"]), \
             patch.object(cv2, "imread", return_value="fake_img"), \
             patch.object(tptm, "slice_badge_rows", return_value=["row0"] + [None] * 5), \
             patch.object(tptm, "identify_row_types_multi_frame", return_value=fake_result), \
             patch.object(tptm, "narrow_species_by_types", return_value=["Kingambit"]):
            roster, _had_failure = am.read_roster(
                None, "model", "model", "ffmpeg", "video.mp4", 100, "workdir", "")

        self.assertEqual(roster["opponent_team"], ["Kingambit"])
        self.assertEqual(roster["type_badge_overrides"],
                         [{"row": 0, "was": "Heracross", "now": "Kingambit",
                           "identified_types": ["dark", "steel"]}])


if __name__ == "__main__":
    unittest.main()
