"""
Tests for analyze_matches.py's nearest_frame()/attach_reference_frames()/
prune_unreferenced_frames() - what lets the dashboard show the actual frame
the AI was looking at for a given event, so a user can visually verify (or
correct) a wrong call instead of just taking the AI's word for it. See
ARCHITECTURE_HANDOFF.md's data-retention note and CODE_EXPLAINED.md's
write-up of `reference_frame`.

nearest_frame/attach_reference_frames are pure logic, no video/FFmpeg/
network involved - `frames` is just whatever (path, timestamp) list happened
to be sampled. prune_unreferenced_frames does real filesystem I/O (deletes
files), so its tests use a real tempfile.TemporaryDirectory rather than
mocking os.listdir/os.remove - cheap enough for this to not be worth mocking,
and it exercises the actual path-matching logic against real files.

Run: py -m unittest tests.test_reference_frames -v   (from poc-starter/)
"""

import os
import tempfile
import unittest

import analyze_matches as am


class TestNearestFrame(unittest.TestCase):
    def test_picks_the_closest_timestamp(self):
        frames = [("a.jpg", 0.0), ("b.jpg", 10.0), ("c.jpg", 20.0)]
        self.assertEqual(am.nearest_frame(frames, 11.0), "b.jpg")
        self.assertEqual(am.nearest_frame(frames, 19.9), "c.jpg")
        self.assertEqual(am.nearest_frame(frames, 0.4), "a.jpg")

    def test_exact_match_wins(self):
        frames = [("a.jpg", 5.0), ("b.jpg", 15.0)]
        self.assertEqual(am.nearest_frame(frames, 15.0), "b.jpg")

    def test_empty_frames_returns_none(self):
        self.assertIsNone(am.nearest_frame([], 10.0))

    def test_unusable_timestamp_returns_none_not_a_crash(self):
        frames = [("a.jpg", 0.0)]
        for bad in (None, "not-a-number", object()):
            with self.subTest(bad=bad):
                self.assertIsNone(am.nearest_frame(frames, bad))


class TestAttachReferenceFrames(unittest.TestCase):
    def test_tags_every_event_with_a_timestamp(self):
        events = [
            {"timestamp": 1.0, "event": "move_used", "pokemon": "Mawile"},
            {"timestamp": 9.0, "event": "pokemon_fainted", "pokemon": "Salazzle"},
        ]
        frames = [("f0.jpg", 0.0), ("f1.jpg", 10.0)]
        am.attach_reference_frames(events, frames)
        self.assertEqual(events[0]["reference_frame"], "f0.jpg")
        self.assertEqual(events[1]["reference_frame"], "f1.jpg")

    def test_events_without_a_timestamp_are_left_alone(self):
        """team_preview/battle_end-style synthetic events might not always
        carry a plain numeric timestamp in every caller - must not crash or
        add a bogus reference_frame."""
        events = [{"event": "some_summary_event", "detail": "no timestamp here"}]
        am.attach_reference_frames(events, [("f0.jpg", 0.0)])
        self.assertNotIn("reference_frame", events[0])

    def test_no_frames_is_a_no_op(self):
        events = [{"timestamp": 5.0, "event": "move_used"}]
        result = am.attach_reference_frames(events, [])
        self.assertNotIn("reference_frame", events[0])
        self.assertIs(result, events)

    def test_mutates_and_returns_the_same_list(self):
        events = [{"timestamp": 1.0, "event": "move_used"}]
        frames = [("f0.jpg", 1.0)]
        result = am.attach_reference_frames(events, frames)
        self.assertIs(result, events)
        self.assertEqual(result[0]["reference_frame"], "f0.jpg")


class TestPruneUnreferencedFrames(unittest.TestCase):
    def _make_frames(self, tmpdir, names):
        for name in names:
            with open(os.path.join(tmpdir, name), "w") as f:
                f.write("fake jpg bytes")

    def test_keeps_only_referenced_frames(self):
        """A match_workdir with roster (prevN_), battle (b_), and winner
        (resN_) frames - only b_00002.jpg was ever picked as a
        reference_frame, so it's the only survivor."""
        with tempfile.TemporaryDirectory() as tmp:
            names = ["prev0_00001.jpg", "b_00001.jpg", "b_00002.jpg", "res0_00001.jpg"]
            self._make_frames(tmp, names)
            kept_path = os.path.join(tmp, "b_00002.jpg")
            events = [{"timestamp": 5.0, "event": "move_used", "reference_frame": kept_path}]

            am.prune_unreferenced_frames(tmp, events)

            remaining = set(os.listdir(tmp))
            self.assertEqual(remaining, {"b_00002.jpg"})

    def test_no_reference_frame_on_any_event_prunes_everything(self):
        """Documented behavior, not an accident: if nothing was tagged (e.g.
        battle-event extraction found zero events), there's nothing worth
        keeping, so every sampled frame for this match gets removed."""
        with tempfile.TemporaryDirectory() as tmp:
            self._make_frames(tmp, ["prev0_00001.jpg", "b_00001.jpg"])
            events = [{"event": "team_preview", "detail": "no timestamp/frame here"}]

            am.prune_unreferenced_frames(tmp, events)

            self.assertEqual(os.listdir(tmp), [])

    def test_nonexistent_directory_is_a_noop(self):
        """A match that failed before ever sampling any frames (or a stale
        match_workdir path) shouldn't raise."""
        missing = os.path.join(tempfile.gettempdir(), "definitely_does_not_exist_12345")
        am.prune_unreferenced_frames(missing, [{"reference_frame": "whatever.jpg"}])  # must not raise

    def test_multiple_events_can_share_one_kept_frame(self):
        """Two events close enough in time can point at the same nearest
        frame (see nearest_frame) - that frame must survive, and pruning
        must not double-count or error on the repeat."""
        with tempfile.TemporaryDirectory() as tmp:
            self._make_frames(tmp, ["b_00001.jpg", "b_00002.jpg"])
            shared = os.path.join(tmp, "b_00001.jpg")
            events = [
                {"timestamp": 1.0, "event": "move_used", "reference_frame": shared},
                {"timestamp": 1.2, "event": "pokemon_fainted", "reference_frame": shared},
            ]

            am.prune_unreferenced_frames(tmp, events)

            self.assertEqual(os.listdir(tmp), ["b_00001.jpg"])


if __name__ == "__main__":
    unittest.main()
