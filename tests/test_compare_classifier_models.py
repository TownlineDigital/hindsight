"""
Tests for compare_classifier_models.py's comparison logic. structure_pass.classify()
itself needs a real API key/network call, so it's replaced with a fake here that
returns pre-baked label lists - this tests the actual decision-relevant logic
(agreement rate, disagreement collection) without needing google-genai installed
or any network access.

Run: py -m unittest tests.test_compare_classifier_models -v   (from poc-starter/)
"""

import os
import sys
import unittest
from unittest.mock import patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import compare_classifier_models as ccm  # noqa: E402


class TestCompare(unittest.TestCase):
    def _fake_frames(self, n):
        return [(f"frame{i}.jpg", float(i * 10)) for i in range(n)]

    def test_perfect_agreement(self):
        frames = self._fake_frames(5)
        labels = ["battle", "battle", "menu", "result", "other"]

        def fake_classify(frames_arg, model, batch, concurrency):
            return [(ts, lab) for (_, ts), lab in zip(frames_arg, labels)]

        with patch.object(ccm.sp, "classify", side_effect=fake_classify):
            rate, disagreements = ccm.compare(frames, "model-a", "model-b", 20, 6)

        self.assertEqual(rate, 1.0)
        self.assertEqual(disagreements, [])

    def test_detects_and_reports_disagreements(self):
        frames = self._fake_frames(4)
        labels_a = ["battle", "menu", "result", "other"]
        labels_b = ["battle", "other", "result", "team_preview"]   # disagrees on index 1 and 3

        def fake_classify(frames_arg, model, batch, concurrency):
            labels = labels_a if model == "model-a" else labels_b
            return [(ts, lab) for (_, ts), lab in zip(frames_arg, labels)]

        with patch.object(ccm.sp, "classify", side_effect=fake_classify):
            rate, disagreements = ccm.compare(frames, "model-a", "model-b", 20, 6)

        self.assertEqual(rate, 0.5)   # 2 of 4 agree
        self.assertEqual(len(disagreements), 2)
        self.assertEqual(disagreements[0], (10.0, "menu", "other"))
        self.assertEqual(disagreements[1], (30.0, "other", "team_preview"))

    def test_empty_frames_returns_zero_rate_not_a_crash(self):
        def fake_classify(frames_arg, model, batch, concurrency):
            return []

        with patch.object(ccm.sp, "classify", side_effect=fake_classify):
            rate, disagreements = ccm.compare([], "model-a", "model-b", 20, 6)

        self.assertEqual(rate, 0.0)
        self.assertEqual(disagreements, [])


if __name__ == "__main__":
    unittest.main()
