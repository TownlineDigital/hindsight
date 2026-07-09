"""
Tests for coach_chat.py's session-boundary-aware additions
(_format_session_date, session_progression_summary) - the piece that lets the
/career/coach endpoint answer "have I improved" questions by giving the model
a per-session breakdown instead of one flat, all-time-blended profile (see
backend/career.py and backend/main.py's career_coach() for how this gets
wired up with real cross-job data).

Doesn't re-test profile_summary()/by_match() themselves (pre-existing,
unchanged logic) - only the new session-grouping wrapper around them.

Run: py -m unittest tests.test_coach_chat_sessions -v   (from poc-starter/)
"""

import sys
import types
import unittest


def _ensure_stub(name, attrs):
    """coach_chat.py needs google.genai at import time - stub it if the real
    package isn't installed (these tests never call anything from it)."""
    try:
        __import__(name)
        return False
    except ImportError:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
        return True


_ensure_stub("google", {})
_ensure_stub("google.genai", {"Client": object})
_ensure_stub("google.genai.types", {"GenerateContentConfig": object})

import coach_chat as cc   # noqa: E402


def _match_events(match_n, won):
    return [
        {"event": "team_preview", "match": match_n,
         "player_lead": "Rotom, Incineroar",
         "player_brought": "Rotom, Incineroar, Whimsicott, Rillaboom"},
        {"event": "pokemon_fainted", "match": match_n,
         "actor": "opponent" if won else "player", "timestamp": 10},
        {"event": "battle_end", "match": match_n, "winner": "player" if won else "opponent"},
    ]


class TestFormatSessionDate(unittest.TestCase):

    def test_float_epoch(self):
        # 2025-06-01T00:00:00Z
        result = cc._format_session_date(1748736000.0)
        self.assertEqual(result, "2025-06-01")

    def test_iso_string_with_z(self):
        self.assertEqual(cc._format_session_date("2025-06-01T00:00:00Z"), "2025-06-01")

    def test_iso_string_with_offset(self):
        self.assertEqual(cc._format_session_date("2025-06-01T00:00:00+00:00"), "2025-06-01")

    def test_none_returns_placeholder(self):
        self.assertEqual(cc._format_session_date(None), "unknown date")

    def test_unparseable_returns_placeholder_not_crash(self):
        self.assertEqual(cc._format_session_date("not-a-real-date"), "unknown date")


class TestSessionProgressionSummary(unittest.TestCase):

    def _events_and_sessions(self):
        events = []
        for e in _match_events(1, won=False):
            e["session"] = 1
            events.append(e)
        for e in _match_events(2, won=False):
            e["session"] = 1
            events.append(e)
        for e in _match_events(3, won=True):
            e["session"] = 2
            events.append(e)
        sessions = [
            {"session": 1, "job_id": "job1", "created_at": 1748736000.0, "matches_in_session": 2},
            {"session": 2, "job_id": "job2", "created_at": 1751328000.0, "matches_in_session": 1},
        ]
        return events, sessions

    def test_produces_one_block_per_session_in_order(self):
        events, sessions = self._events_and_sessions()
        summary = cc.session_progression_summary(events, sessions)
        idx1 = summary.find("SESSION 1")
        idx2 = summary.find("SESSION 2")
        self.assertNotEqual(idx1, -1)
        self.assertNotEqual(idx2, -1)
        self.assertLess(idx1, idx2)   # oldest first

    def test_includes_per_session_record_not_blended(self):
        events, sessions = self._events_and_sessions()
        summary = cc.session_progression_summary(events, sessions)
        # session 1: 0-2 (lost both); session 2: 1-0 (won) - each block's own
        # RECORD line must reflect ONLY that session, not the blended 1-2 total.
        session1_block = summary[summary.find("SESSION 1"):summary.find("SESSION 2")]
        session2_block = summary[summary.find("SESSION 2"):]
        self.assertIn("RECORD: 0-2", session1_block)
        self.assertIn("RECORD: 1-0", session2_block)

    def test_includes_job_id_and_match_count_in_header(self):
        events, sessions = self._events_and_sessions()
        summary = cc.session_progression_summary(events, sessions)
        self.assertIn("job1", summary)
        self.assertIn("job2", summary)
        self.assertIn("2 matches", summary)   # session 1 has 2 matches
        self.assertIn("1 match,", summary)    # session 2 has 1 match (singular, no trailing 's')

    def test_session_with_no_events_is_skipped_not_blank_block(self):
        events, sessions = self._events_and_sessions()
        sessions_with_empty = sessions + [{"session": 3, "job_id": "job3", "created_at": 999.0, "matches_in_session": 0}]
        summary = cc.session_progression_summary(events, sessions_with_empty)
        self.assertNotIn("SESSION 3", summary)

    def test_empty_sessions_list_returns_empty_string(self):
        self.assertEqual(cc.session_progression_summary([], []), "")

    def test_header_frames_this_as_progression_not_a_flat_dump(self):
        events, sessions = self._events_and_sessions()
        summary = cc.session_progression_summary(events, sessions)
        self.assertTrue(summary.startswith("SESSION-BY-SESSION PROGRESSION"))


if __name__ == "__main__":
    unittest.main()
