"""
Tests for grade_matches.py's pure logic (CSV merge behavior, system-read
extraction) - NOT the video/ffmpeg-dependent frame extraction, which needs
real footage and is exercised by hand via the tool itself, not this suite.

Run: py -m unittest tests.test_grade_matches -v   (from poc-starter/)
"""

import csv
import os
import tempfile
import unittest

import grade_matches as gm


class TestSystemReadForMatch(unittest.TestCase):
    def test_pulls_roster_and_winner_for_the_right_match_only(self):
        events = [
            {"match": 3, "event": "team_preview", "player_team": "Mawile, Grimmsnarl",
             "opponent_team": "Dragalge, Musharna", "player_brought": "Mawile, Grimmsnarl",
             "opponent_brought": "Dragalge, Musharna", "illegal_species_detected": []},
            {"match": 3, "event": "battle_end", "winner": "player", "detail": "You won!"},
            {"match": 4, "event": "team_preview", "player_team": "Charizard", "opponent_team": "Whimsicott"},
            {"match": 4, "event": "battle_end", "winner": "opponent", "detail": "You lost!"},
        ]
        r = gm.system_read_for_match(events, 3)
        self.assertEqual(r["winner"], "player")
        self.assertEqual(r["player_team"], "Mawile, Grimmsnarl")
        self.assertNotIn("Charizard", r["player_team"])

    def test_missing_match_returns_unknown_winner_not_a_crash(self):
        r = gm.system_read_for_match([], 99)
        self.assertEqual(r["winner"], "unknown")


class TestUpsertGradeRows(unittest.TestCase):
    def test_regrading_one_match_does_not_touch_a_hand_graded_other_match(self):
        """Real bug caught while building this: a str/int mismatch between
        freshly-built rows (int match) and CSV-read rows (str match) meant
        re-grading a match appended a duplicate row instead of replacing the
        old one, silently discarding nothing but also never actually
        updating - this guards against that regression."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "grade_accuracy.csv")
            base_row = lambda m, roster: {
                "match": m, "system_roster": roster, "system_brought": "", "system_illegal": "",
                "system_winner": "player", "system_winner_detail": "", "actual_roster": "",
                "actual_winner": "", "correct?": "", "notes": "",
            }
            gm.upsert_grade_rows(path, [base_row(3, "A"), base_row(14, "C")])

            # simulate hand-grading match 3
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            for r in rows:
                if r["match"] == "3":
                    r["correct?"] = "yes"
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=rows[0].keys())
                w.writeheader()
                w.writerows(rows)

            # re-grade ONLY match 14
            gm.upsert_grade_rows(path, [base_row(14, "C2")])

            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 2, f"expected exactly 2 rows (no duplicates), got {len(rows)}")
            m3 = next(r for r in rows if r["match"] == "3")
            m14 = next(r for r in rows if r["match"] == "14")
            self.assertEqual(m3["correct?"], "yes", "hand-graded match 3 must survive re-grading match 14")
            self.assertEqual(m14["system_roster"], "C2", "match 14 must be updated to the new system read")


if __name__ == "__main__":
    unittest.main()
