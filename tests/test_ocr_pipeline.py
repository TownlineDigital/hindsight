"""
Tests for ocr_pipeline.py - the tiered-merge layer that combines OCR-
derived events (from ocr_battle_reader.py + battle_text_parser.py) with
Gemini's existing vision-derived events, and resolves any Pokemon nickname
via pokemon_identity.py (see the module's own docstring and
ARCHITECTURE_HANDOFF.md's OCR write-up for the full reasoning).

Pure logic - `extract_ocr_events` is exercised via a fake `sample_window_fn`
(no ffmpeg/real video needed) and real OCR frames aren't re-tested here
(that's ocr_battle_reader.py's/battle_text_parser.py's own job); everything
else (merge, dedupe, name resolution) needs no OCR/video/network at all.
`identify_pokemon_species`'s real Gemini call is exercised via a fake
call_fn, never a real API call.

Run: py -m unittest tests.test_ocr_pipeline -v   (from poc-starter/)
"""

import os
import sys
import unittest
from unittest.mock import patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import ocr_pipeline as op  # noqa: E402
from pokemon_identity import IdentityResolver  # noqa: E402


def _ev(timestamp, event, pokemon=None, detail="", confidence=0.9, **extra):
    e = {"timestamp": timestamp, "event": event, "pokemon": pokemon,
         "detail": detail, "confidence": confidence}
    e.update(extra)
    return e


class TestDedupeConsecutive(unittest.TestCase):
    def test_collapses_the_same_event_seen_across_several_frames(self):
        """A banner is on screen across multiple consecutive OCR-sampled
        frames - each one would otherwise re-report the identical action."""
        events = [
            _ev(10.0, "move_used", "Greninja", "Hydro Pump"),
            _ev(10.5, "move_used", "Greninja", "Hydro Pump"),
            _ev(11.0, "move_used", "Greninja", "Hydro Pump"),
        ]
        out = op._dedupe_consecutive(events)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["timestamp"], 10.0)

    def test_does_not_collapse_events_outside_the_window(self):
        events = [
            _ev(10.0, "move_used", "Greninja", "Hydro Pump"),
            _ev(20.0, "move_used", "Greninja", "Hydro Pump"),
        ]
        out = op._dedupe_consecutive(events, window_s=3.0)
        self.assertEqual(len(out), 2)

    def test_does_not_collapse_genuinely_different_events(self):
        events = [
            _ev(10.0, "move_used", "Greninja", "Hydro Pump"),
            _ev(10.5, "critical_hit", "Greninja", ""),
        ]
        out = op._dedupe_consecutive(events)
        self.assertEqual(len(out), 2)

    def test_mirror_match_does_not_collapse_the_same_species_on_different_sides(self):
        """Both players can legally run the same species (Species Clause only
        bars duplicates on ONE team). If both sides' Whimsicott use Protect
        within the same couple seconds, that's two real, distinct events -
        not one banner staying on screen - and must not collapse into one
        just because event/pokemon/detail all match."""
        events = [
            _ev(10.0, "move_used", "Whimsicott", "Protect", actor="player"),
            _ev(10.5, "move_used", "Whimsicott", "Protect", actor="opponent"),
        ]
        out = op._dedupe_consecutive(events)
        self.assertEqual(len(out), 2)
        self.assertEqual({e["actor"] for e in out}, {"player", "opponent"})

    def test_still_collapses_when_actor_is_unknown_on_either_side(self):
        """battle_text_parser only sets `actor` when the banner text itself
        discloses a side (see its own docstring) - it's frequently None. When
        we can't positively confirm the two events are on different sides,
        the old collapse-as-repeat behavior must still apply, or a real
        repeated banner would start duplicating again."""
        events = [
            _ev(10.0, "move_used", "Whimsicott", "Protect"),
            _ev(10.5, "move_used", "Whimsicott", "Protect", actor="opponent"),
        ]
        out = op._dedupe_consecutive(events)
        self.assertEqual(len(out), 1)


class TestExtractOcrEvents(unittest.TestCase):
    """Uses a fake sample_window_fn / cv2.imread / ocr.read_bottom_banner so
    no real ffmpeg, video file, or Tesseract install is needed to test the
    wiring itself."""

    def test_wires_banner_text_through_the_parser_and_tags_events(self):
        fake_frames = [("frame_a.jpg", 10.0), ("frame_b.jpg", 10.5)]

        def fake_sample_window(ffmpeg, video, start, dur, fps, out_dir, prefix, hwaccel, scale_w):
            return fake_frames

        with patch.object(op.cv2, "imread", return_value="not-none-sentinel"), \
             patch.object(op.ocr, "read_bottom_banner", return_value="A critical hit!"):
            events = op.extract_ocr_events(fake_sample_window, "ffmpeg", "video.mp4", 0, 20, "workdir")

        self.assertEqual(len(events), 1)   # both frames produce the identical
                                            # event and get deduped into one
        e = events[0]
        self.assertEqual(e["event"], "critical_hit")
        self.assertEqual(e["source"], "ocr")
        self.assertEqual(e["reference_frame"], "frame_a.jpg")

    def test_frames_with_no_legible_text_produce_no_events(self):
        def fake_sample_window(ffmpeg, video, start, dur, fps, out_dir, prefix, hwaccel, scale_w):
            return [("frame_a.jpg", 10.0)]

        with patch.object(op.cv2, "imread", return_value="not-none-sentinel"), \
             patch.object(op.ocr, "read_bottom_banner", return_value=""):
            events = op.extract_ocr_events(fake_sample_window, "ffmpeg", "video.mp4", 0, 20, "workdir")
        self.assertEqual(events, [])

    def test_unreadable_frame_file_is_skipped_not_a_crash(self):
        def fake_sample_window(ffmpeg, video, start, dur, fps, out_dir, prefix, hwaccel, scale_w):
            return [("missing.jpg", 10.0)]

        with patch.object(op.cv2, "imread", return_value=None):
            events = op.extract_ocr_events(fake_sample_window, "ffmpeg", "video.mp4", 0, 20, "workdir")
        self.assertEqual(events, [])

    def test_accepts_pre_sampled_frames_without_calling_sample_window_fn_again(self):
        """When a caller already sampled the OCR window via sample_ocr_frames()
        (e.g. to also pass the raw list to attach_reference_frames'
        quality_frames - see analyze_matches.py), passing frames= must skip
        re-sampling entirely, not just accept the parameter and ignore it."""
        pre_sampled = [("frame_a.jpg", 10.0)]

        def fake_sample_window(*a, **k):
            raise AssertionError("sample_window_fn must not be called when frames= is given")

        with patch.object(op.cv2, "imread", return_value="not-none-sentinel"), \
             patch.object(op.ocr, "read_bottom_banner", return_value="A critical hit!"):
            events = op.extract_ocr_events(
                fake_sample_window, "ffmpeg", "video.mp4", 0, 20, "workdir", frames=pre_sampled)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["reference_frame"], "frame_a.jpg")


class TestSampleOcrFrames(unittest.TestCase):

    def test_delegates_to_sample_window_fn_with_ocr_fps_and_scale(self):
        captured = {}

        def fake_sample_window(ffmpeg, video, start, dur, fps, out_dir, prefix, hwaccel, scale_w):
            captured.update(fps=fps, scale_w=scale_w, prefix=prefix, start=start, dur=dur)
            return [("ocr_a.jpg", 5.0), ("ocr_b.jpg", 5.5)]

        frames = op.sample_ocr_frames(fake_sample_window, "ffmpeg", "video.mp4", 5, 15, "workdir")

        self.assertEqual(frames, [("ocr_a.jpg", 5.0), ("ocr_b.jpg", 5.5)])
        self.assertEqual(captured["fps"], op.OCR_FPS)
        self.assertEqual(captured["scale_w"], op.OCR_SCALE_W)
        self.assertEqual(captured["prefix"], "ocr")
        self.assertEqual(captured["start"], 5)
        self.assertEqual(captured["dur"], 10)  # end - start


class TestResolveOcrPokemonNames(unittest.TestCase):
    def test_roster_species_resolves_for_free_no_vision_call(self):
        events = [_ev(1.0, "move_used", "Charizard", "Flamethrower")]
        resolver = IdentityResolver(known_species=["Charizard"])
        calls = []
        op.resolve_ocr_pokemon_names(events, resolver, vision_call=lambda n, p: calls.append(n))
        self.assertEqual(events[0]["pokemon"], "Charizard")
        self.assertEqual(calls, [])   # never invoked - resolved cheaply

    def test_genuine_nickname_triggers_exactly_one_vision_call_then_is_cached(self):
        events = [
            _ev(1.0, "move_used", "Big Red", "Flamethrower", **{"reference_frame": "f1.jpg"}),
            _ev(5.0, "pokemon_fainted", "Big Red", **{"reference_frame": "f2.jpg"}),
        ]
        resolver = IdentityResolver(known_species=["Charizard", "Staraptor"])
        calls = []

        def fake_vision_call(name, path):
            calls.append((name, path))
            return "Charizard"

        op.resolve_ocr_pokemon_names(events, resolver, vision_call=fake_vision_call)

        self.assertEqual(events[0]["pokemon"], "Charizard")
        self.assertEqual(events[1]["pokemon"], "Charizard")
        # Only the FIRST occurrence should need a real vision call - the
        # second is answered from the resolver's cache (learn()).
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "Big Red")

    def test_unresolvable_nickname_with_no_vision_call_is_flagged_not_dropped(self):
        events = [_ev(1.0, "move_used", "Big Red", "Flamethrower", confidence=0.95)]
        resolver = IdentityResolver(known_species=["Charizard"])
        op.resolve_ocr_pokemon_names(events, resolver, vision_call=None)
        self.assertEqual(events[0]["pokemon"], "Big Red")   # kept, not blanked
        self.assertLessEqual(events[0]["confidence"], 0.3)
        self.assertIn("unresolved nickname", events[0]["detail"])

    def test_vision_call_that_fails_falls_back_to_the_flagged_path(self):
        events = [_ev(1.0, "move_used", "Big Red", "Flamethrower")]
        resolver = IdentityResolver(known_species=["Charizard"])

        def failing_vision_call(name, path):
            raise RuntimeError("API down")

        op.resolve_ocr_pokemon_names(events, resolver, vision_call=failing_vision_call)
        self.assertEqual(events[0]["pokemon"], "Big Red")
        self.assertLessEqual(events[0]["confidence"], 0.3)

    def test_blank_pokemon_field_is_left_alone(self):
        events = [_ev(1.0, "weather_or_terrain_set", pokemon=None)]
        resolver = IdentityResolver(known_species=["Charizard"])
        op.resolve_ocr_pokemon_names(events, resolver, vision_call=lambda n, p: "x")
        self.assertIsNone(events[0]["pokemon"])


class TestIdentifyPokemonSpecies(unittest.TestCase):
    def test_calls_call_fn_with_the_prompt_and_image_and_returns_species(self):
        captured = {}

        def fake_call_fn(prompt, paths):
            captured["prompt"] = prompt
            captured["paths"] = paths
            return {"species": "Charizard"}

        result = op.identify_pokemon_species(fake_call_fn, "Big Red", "frame.jpg")
        self.assertEqual(result, "Charizard")
        self.assertIn("Big Red", captured["prompt"])
        self.assertEqual(captured["paths"], ["frame.jpg"])

    def test_missing_image_path_short_circuits_without_calling(self):
        def fake_call_fn(prompt, paths):
            raise AssertionError("should not be called with no image")
        self.assertIsNone(op.identify_pokemon_species(fake_call_fn, "Big Red", None))

    def test_call_fn_exception_returns_none(self):
        def failing_call_fn(prompt, paths):
            raise RuntimeError("network error")
        self.assertIsNone(op.identify_pokemon_species(failing_call_fn, "Big Red", "frame.jpg"))

    def test_non_dict_response_returns_none(self):
        def fake_call_fn(prompt, paths):
            return None
        self.assertIsNone(op.identify_pokemon_species(fake_call_fn, "Big Red", "frame.jpg"))


class TestMergeOcrAndVisionEvents(unittest.TestCase):
    def test_ocr_event_wins_over_a_duplicate_vision_event(self):
        ocr_events = [_ev(10.0, "pokemon_fainted", "Staraptor", "The opposing Staraptor fainted!",
                          confidence=0.95, source="ocr")]
        vision_events = [_ev(11.0, "pokemon_fainted", "Staraptor", "fainted", confidence=0.6)]
        merged = op.merge_ocr_and_vision_events(ocr_events, vision_events, window_s=4.0)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["source"], "ocr")

    def test_non_duplicate_vision_events_pass_through_untouched(self):
        """field_state / hp_change events aren't something OCR here covers
        at all - they must never be dropped just because SOME ocr event
        exists in the same match."""
        ocr_events = [_ev(10.0, "critical_hit", "Greninja", source="ocr")]
        vision_events = [_ev(12.0, "field_state", None, "board state")]
        merged = op.merge_ocr_and_vision_events(ocr_events, vision_events)
        self.assertEqual(len(merged), 2)

    def test_vision_event_far_outside_the_window_is_not_treated_as_duplicate(self):
        ocr_events = [_ev(10.0, "move_used", "Greninja", source="ocr")]
        vision_events = [_ev(60.0, "move_used", "Greninja")]
        merged = op.merge_ocr_and_vision_events(ocr_events, vision_events, window_s=4.0)
        self.assertEqual(len(merged), 2)

    def test_result_is_sorted_by_timestamp(self):
        ocr_events = [_ev(50.0, "critical_hit", "Greninja", source="ocr")]
        vision_events = [_ev(5.0, "team_preview", None)]
        merged = op.merge_ocr_and_vision_events(ocr_events, vision_events)
        self.assertEqual([e["timestamp"] for e in merged], [5.0, 50.0])

    def test_vision_event_with_unparseable_timestamp_is_kept_not_crashed_on(self):
        ocr_events = [_ev(10.0, "move_used", "Greninja", source="ocr")]
        vision_events = [_ev("not-a-number", "field_state", None)]
        merged = op.merge_ocr_and_vision_events(ocr_events, vision_events)
        self.assertEqual(len(merged), 2)

    def test_mirror_match_keeps_both_sides_vision_event_instead_of_dropping_it(self):
        """The whole reason `is_duplicate` exists is to drop a vision event
        that's clearly re-describing something OCR already caught. But if
        BOTH players are running the same species, an OCR read of the
        OPPONENT's Whimsicott using Protect must never cause a real vision
        event about the PLAYER's own Whimsicott (nearby in time) to be
        silently dropped as if it were the same action."""
        ocr_events = [_ev(10.0, "move_used", "Whimsicott", "Protect",
                          confidence=0.95, source="ocr", actor="opponent")]
        vision_events = [_ev(11.0, "move_used", "Whimsicott", "Protect",
                             confidence=0.7, actor="player")]
        merged = op.merge_ocr_and_vision_events(ocr_events, vision_events, window_s=4.0)
        self.assertEqual(len(merged), 2)
        self.assertEqual({e["actor"] for e in merged}, {"player", "opponent"})

    def test_still_drops_duplicate_vision_event_when_actor_is_unknown(self):
        """Same fallback as the dedupe side: when we can't positively confirm
        the OCR and vision events are on different sides, the original
        drop-the-vision-duplicate behavior must still apply."""
        ocr_events = [_ev(10.0, "move_used", "Whimsicott", "Protect",
                          confidence=0.95, source="ocr")]
        vision_events = [_ev(11.0, "move_used", "Whimsicott", "Protect", confidence=0.7)]
        merged = op.merge_ocr_and_vision_events(ocr_events, vision_events, window_s=4.0)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["source"], "ocr")


if __name__ == "__main__":
    unittest.main()
