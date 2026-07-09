"""
Tests for frame_dedup.py - fully verifiable without any API, video, or the
rest of the pipeline: just real image files generated on the fly and real
OpenCV calls.

Run: py -m unittest tests.test_frame_dedup -v   (from poc-starter/)
"""

import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import cv2  # noqa: E402
import frame_dedup as fd  # noqa: E402


class TestFrameDedup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_solid(self, name, value):
        """A flat-color 100x100 image - two calls with the same `value`
        are near-identical; different values are clearly different."""
        path = os.path.join(self.tmp, name)
        img = np.full((100, 100), value, dtype=np.uint8)
        cv2.imwrite(path, img)
        return path

    def _write_noisy(self, name, value, noise=3, seed=0):
        """Same base color plus tiny random noise - simulates real video
        compression artifacts between two frames of the same static screen."""
        path = os.path.join(self.tmp, name)
        rng = np.random.default_rng(seed)
        img = np.clip(value + rng.integers(-noise, noise + 1, (100, 100)), 0, 255).astype(np.uint8)
        cv2.imwrite(path, img)
        return path

    def test_identical_images_score_zero(self):
        a = self._write_solid("a.jpg", 128)
        b = self._write_solid("b.jpg", 128)
        self.assertEqual(fd.frame_difference_score(a, b), 0.0)

    def test_very_different_images_score_high(self):
        black = self._write_solid("black.jpg", 0)
        white = self._write_solid("white.jpg", 255)
        self.assertGreater(fd.frame_difference_score(black, white), 200)

    def test_compression_noise_scores_low(self):
        """Two frames of the same static screen, with realistic tiny
        per-pixel noise, must score BELOW the default threshold - this is
        the exact case the whole feature exists to collapse."""
        a = self._write_noisy("a.jpg", 128, noise=3, seed=1)
        b = self._write_noisy("b.jpg", 128, noise=3, seed=2)
        score = fd.frame_difference_score(a, b)
        self.assertLess(score, 2.0, f"realistic compression noise scored {score}, would wrongly NOT be deduped")

    def test_unreadable_image_never_treated_as_duplicate(self):
        missing = os.path.join(self.tmp, "does_not_exist.jpg")
        real = self._write_solid("real.jpg", 100)
        self.assertEqual(fd.frame_difference_score(missing, real), float("inf"))


class TestDedupeFrames(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _solid(self, name, value):
        path = os.path.join(self.tmp, name)
        cv2.imwrite(path, np.full((100, 100), value, dtype=np.uint8))
        return path

    def test_collapses_a_long_run_of_static_frames_to_one(self):
        """5 frames of the same static screen (held across several sample
        intervals) should collapse to just the first - this is the actual
        cost-saving scenario (a long dialogue box, a paused moment)."""
        frames = [(self._solid(f"static{i}.jpg", 128), float(i)) for i in range(5)]
        kept = fd.dedupe_frames(frames, threshold=2.0)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0][1], 0.0)   # keeps the FIRST one, with its real timestamp

    def test_keeps_frames_that_actually_change(self):
        """Static, static, CHANGE, static, static -> keeps 2: the first of
        the initial run, and the first of the new (changed) run."""
        frames = [
            (self._solid("a0.jpg", 50), 0.0),
            (self._solid("a1.jpg", 50), 1.0),
            (self._solid("b0.jpg", 200), 2.0),   # real change
            (self._solid("b1.jpg", 200), 3.0),
            (self._solid("b2.jpg", 200), 4.0),
        ]
        kept = fd.dedupe_frames(frames, threshold=2.0)
        self.assertEqual([ts for _, ts in kept], [0.0, 2.0])

    def test_compares_against_last_KEPT_frame_not_last_frame_seen(self):
        """A slow drift where each step differs only slightly from its
        immediate predecessor, but the far ends are very different, must
        still eventually register the real change - proves comparison is
        against the last KEPT frame's actual pixels, not a rolling
        "did anything change since one step ago" check that could drift
        arbitrarily far without ever triggering."""
        # Small, steady per-step increments that would each individually be
        # "not different enough", but accumulate past the threshold overall.
        frames = [(self._solid(f"drift{i}.jpg", 100 + i), float(i)) for i in range(0, 40, 1)]
        kept = fd.dedupe_frames(frames, threshold=2.0)
        # Must keep more than just the first frame - the drift eventually
        # exceeds the threshold relative to whatever was last kept.
        self.assertGreater(len(kept), 1)

    def test_threshold_zero_disables_dedup(self):
        frames = [(self._solid("x.jpg", 100), 0.0), (self._solid("y.jpg", 100), 1.0)]
        kept = fd.dedupe_frames(frames, threshold=0)
        self.assertEqual(len(kept), 2)

    def test_empty_input(self):
        self.assertEqual(fd.dedupe_frames([]), [])


if __name__ == "__main__":
    unittest.main()
