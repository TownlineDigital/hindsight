"""
Tests for frame_quality.py - the free, local sharpness scoring used to pick
the best nearby sampled frame instead of just the nearest-in-time one. See
that module's own docstring and analyze_matches.attach_reference_frames'
docstring for how this fits into the wider reference-frame-selection change.

Uses real synthetic images (a genuinely sharp, high-frequency pattern vs a
heavily Gaussian-blurred copy of the SAME image) rather than fixed hand-typed
numbers, so the test actually exercises real OpenCV pixel math, not just
mocked return values.
"""

import os
import tempfile
import unittest

import cv2
import numpy as np

import frame_quality as fq


def _checkerboard(size=200, square=4):
    """A real high-frequency pattern (lots of sharp edges) - a good stand-in
    for a crisp real frame with genuine detail."""
    img = np.zeros((size, size), dtype=np.uint8)
    for y in range(0, size, square):
        for x in range(0, size, square):
            if ((x // square) + (y // square)) % 2 == 0:
                img[y:y + square, x:x + square] = 255
    return img


class TestFrameSharpness(unittest.TestCase):

    def test_none_for_unreadable_path(self):
        self.assertIsNone(fq.frame_sharpness(os.path.join(tempfile.gettempdir(), "definitely_missing_12345.png")))

    def test_sharp_image_scores_higher_than_its_own_blurred_copy(self):
        sharp = _checkerboard()
        blurred = cv2.GaussianBlur(sharp, (15, 15), sigmaX=5)
        with tempfile.TemporaryDirectory() as tmp:
            sharp_path = os.path.join(tmp, "sharp.png")
            blurred_path = os.path.join(tmp, "blurred.png")
            cv2.imwrite(sharp_path, sharp)
            cv2.imwrite(blurred_path, blurred)

            sharp_score = fq.frame_sharpness(sharp_path)
            blurred_score = fq.frame_sharpness(blurred_path)

            self.assertIsNotNone(sharp_score)
            self.assertIsNotNone(blurred_score)
            self.assertGreater(sharp_score, blurred_score)

    def test_flat_solid_image_scores_near_zero(self):
        flat = np.full((100, 100), 128, dtype=np.uint8)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "flat.png")
            cv2.imwrite(path, flat)
            score = fq.frame_sharpness(path)
            self.assertIsNotNone(score)
            self.assertAlmostEqual(score, 0.0, places=3)


class TestPickSharpest(unittest.TestCase):

    def test_empty_list_returns_none(self):
        self.assertIsNone(fq.pick_sharpest([]))

    def test_all_unreadable_returns_none(self):
        missing = os.path.join(tempfile.gettempdir(), "definitely_missing_12345.png")
        self.assertIsNone(fq.pick_sharpest([missing, missing + "_2"]))

    def test_picks_the_sharper_of_two_real_images(self):
        sharp = _checkerboard()
        blurred = cv2.GaussianBlur(sharp, (15, 15), sigmaX=5)
        with tempfile.TemporaryDirectory() as tmp:
            sharp_path = os.path.join(tmp, "sharp.png")
            blurred_path = os.path.join(tmp, "blurred.png")
            cv2.imwrite(sharp_path, sharp)
            cv2.imwrite(blurred_path, blurred)

            self.assertEqual(fq.pick_sharpest([blurred_path, sharp_path]), sharp_path)

    def test_skips_unreadable_entries_and_still_finds_the_best_real_one(self):
        sharp = _checkerboard()
        with tempfile.TemporaryDirectory() as tmp:
            sharp_path = os.path.join(tmp, "sharp.png")
            cv2.imwrite(sharp_path, sharp)
            missing = os.path.join(tmp, "missing.png")

            self.assertEqual(fq.pick_sharpest([missing, sharp_path]), sharp_path)


if __name__ == "__main__":
    unittest.main()
