"""
Tests for backend/career.py - the cross-job "career" aggregation that merges
events.json across EVERY completed job a user has uploaded into one
chronological stream, tagged by upload session (see that module's docstring
for why this was missing before: every job already had its own events.json
and already belonged to a user_id, but nothing merged them, so a new upload
started the coach from zero every time).

If `fastapi`/`supabase` aren't installed in this environment, minimal stubs
are injected first (same pattern as tests/test_local_dev_mode.py) - these
tests only exercise the merge/remap/trend logic, never anything from those
real packages.

Run: py -m unittest tests.test_career -v   (from poc-starter/)
"""

import json
import os
import shutil
import sys
import tempfile
import time
import types
import unittest


def _ensure_stub(name, attrs):
    try:
        __import__(name)
        return False
    except ImportError:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
        return True


class _StubHTTPException(Exception):
    def __init__(self, status_code, detail=None):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{status_code}: {detail}")


_ensure_stub("fastapi", {
    "Header": lambda default=None, **kw: default,
    "HTTPException": _StubHTTPException,
})
_ensure_stub("supabase", {
    "Client": object,
    "create_client": lambda url, key: (_ for _ in ()).throw(
        RuntimeError("create_client() should never be called in local dev mode")),
})

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend import auth as auth_module   # noqa: E402
from backend import career                # noqa: E402
from backend import jobs as jobs_module   # noqa: E402


def _team_preview_and_result(match_n, won, session_hint=None):
    """A minimal but realistic 3-event match (team_preview + a fainted +
    battle_end) - just enough for skill_scores.compute_skill_scores and
    coach_chat.profile_summary to compute something real, not just exercise
    the "no data" fallback path."""
    return [
        {"event": "team_preview", "match": match_n,
         "player_lead": "Rotom, Incineroar",
         "player_brought": "Rotom, Incineroar, Whimsicott, Rillaboom"},
        {"event": "pokemon_fainted", "match": match_n,
         "actor": "opponent" if won else "player", "timestamp": 10},
        {"event": "battle_end", "match": match_n, "winner": "player" if won else "opponent"},
    ]


def _make_events(win_pattern):
    """win_pattern: list of bools, one per match (1-indexed in the output)."""
    events = []
    for i, won in enumerate(win_pattern, start=1):
        events.extend(_team_preview_and_result(i, won))
    return events


class _CareerJobSeedingMixin:
    """setUp/_seed_job/_cleanup scaffolding shared by TestCareerMerge and
    TestMatchDurations - deliberately NOT a unittest.TestCase subclass
    itself (a plain mixin), so mixing this into a second test class doesn't
    also inherit and re-run every test_* method already covered by
    TestCareerMerge under a second name."""

    @classmethod
    def setUpClass(cls):
        if auth_module.configured():
            raise unittest.SkipTest("Supabase IS configured in this environment - "
                                     "local-mode tests don't apply here.")

    def setUp(self):
        self._tmp_jobs_dir = tempfile.mkdtemp()
        self._orig_jobs_dir = jobs_module.JOBS_DIR
        jobs_module.JOBS_DIR = type(self._orig_jobs_dir)(self._tmp_jobs_dir)
        jobs_module._LOCAL_JOBS.clear()
        jobs_module._local_discovered = True   # skip folder auto-discovery; we seed _LOCAL_JOBS by hand
        self._job_dirs = []
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        jobs_module.JOBS_DIR = self._orig_jobs_dir
        shutil.rmtree(self._tmp_jobs_dir, ignore_errors=True)
        for d in self._job_dirs:
            shutil.rmtree(d, ignore_errors=True)

    def _seed_job(self, job_id, win_pattern, created_at, user_id, status="done", durations=None):
        """`durations`, if given, is a {local_match: duration_seconds} dict -
        writes a matches.csv alongside events.json the same shape
        structure_pass.py produces (a "match","duration_seconds" column
        pair is all backend/career.py's match_durations() actually reads;
        the other real matches.csv columns aren't needed for these tests)."""
        d = tempfile.mkdtemp()
        self._job_dirs.append(d)
        with open(os.path.join(d, "events.json"), "w", encoding="utf-8") as f:
            json.dump(_make_events(win_pattern), f)
        if durations:
            import csv
            with open(os.path.join(d, "matches.csv"), "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["match", "duration_seconds"])
                w.writeheader()
                for local_m, dur in durations.items():
                    w.writerow({"match": local_m, "duration_seconds": dur})
        jobs_module._LOCAL_JOBS[job_id] = {
            "job_id": job_id, "dir": d, "status": status, "created_at": created_at,
            "user_id": user_id, "source_type": "upload", "video": None,
        }
        return d


class TestCareerMerge(_CareerJobSeedingMixin, unittest.TestCase):
    """These only make sense when Supabase genuinely isn't configured (see
    test_local_dev_mode.py for the identical rationale) - skip rather than
    false-fail against a real configured project (setUpClass's skip check
    lives on the mixin above, shared with TestMatchDurations)."""

    def test_merges_events_from_multiple_completed_jobs(self):
        uid = "user-a"
        self._seed_job("job1", [False, False], created_at=1000.0, user_id=uid)
        self._seed_job("job2", [True, True], created_at=2000.0, user_id=uid)

        merged, sessions = career.merge_user_events(uid)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(len(merged), 12)   # 3 events/match * 2 matches/job * 2 jobs

    def test_sessions_are_chronological_regardless_of_creation_order(self):
        """Seed the NEWER job first (in dict insertion order) - the merge
        must still put it second, since it sorts by created_at, not by
        whatever order jobs.list_jobs() happens to return them in."""
        uid = "user-b"
        self._seed_job("newer", [True], created_at=5000.0, user_id=uid)
        self._seed_job("older", [False], created_at=1000.0, user_id=uid)

        merged, sessions = career.merge_user_events(uid)
        self.assertEqual([s["job_id"] for s in sessions], ["older", "newer"])
        self.assertEqual(sessions[0]["session"], 1)
        self.assertEqual(sessions[1]["session"], 2)

    def test_global_match_numbers_dont_collide_across_jobs(self):
        """Both jobs number their own matches starting at 1 - naive
        concatenation would produce two separate 'match 1's. The merge must
        remap them into one non-colliding global sequence."""
        uid = "user-c"
        self._seed_job("jobA", [True, True], created_at=1000.0, user_id=uid)   # local matches 1, 2
        self._seed_job("jobB", [False, False, False], created_at=2000.0, user_id=uid)  # local matches 1, 2, 3

        merged, sessions = career.merge_user_events(uid)
        global_matches = sorted({e["match"] for e in merged if e.get("match") is not None})
        self.assertEqual(global_matches, [1, 2, 3, 4, 5])   # 2 + 3, no collision
        self.assertEqual(sessions[0]["matches_in_session"], 2)
        self.assertEqual(sessions[1]["matches_in_session"], 3)

    def test_events_are_tagged_with_session_and_source_job_id(self):
        uid = "user-d"
        self._seed_job("job1", [True], created_at=1000.0, user_id=uid)
        self._seed_job("job2", [False], created_at=2000.0, user_id=uid)

        merged, _sessions = career.merge_user_events(uid)
        job1_events = [e for e in merged if e["source_job_id"] == "job1"]
        job2_events = [e for e in merged if e["source_job_id"] == "job2"]
        self.assertTrue(job1_events and all(e["session"] == 1 for e in job1_events))
        self.assertTrue(job2_events and all(e["session"] == 2 for e in job2_events))

    def test_excludes_queued_running_and_failed_jobs(self):
        uid = "user-e"
        self._seed_job("done-job", [True], created_at=1000.0, user_id=uid, status="done")
        self._seed_job("running-job", [True], created_at=2000.0, user_id=uid, status="running")
        self._seed_job("failed-job", [True], created_at=3000.0, user_id=uid, status="failed")

        merged, sessions = career.merge_user_events(uid)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["job_id"], "done-job")
        self.assertTrue(all(e["source_job_id"] == "done-job" for e in merged))

    def test_scoped_to_one_user_only(self):
        self._seed_job("mine", [True], created_at=1000.0, user_id="user-f")
        self._seed_job("theirs", [True], created_at=1000.0, user_id="someone-else")

        merged, sessions = career.merge_user_events("user-f")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["job_id"], "mine")

    def test_no_completed_jobs_returns_empty_not_a_crash(self):
        merged, sessions = career.merge_user_events("nobody-has-uploaded-yet")
        self.assertEqual(merged, [])
        self.assertEqual(sessions, [])

    def test_job_with_missing_events_json_is_skipped_not_crashed(self):
        """A 'done' job whose events.json somehow isn't readable (deleted,
        corrupted) shouldn't take down the whole merge for every other job."""
        uid = "user-g"
        d = tempfile.mkdtemp()
        self._job_dirs.append(d)
        jobs_module._LOCAL_JOBS["broken"] = {
            "job_id": "broken", "dir": d, "status": "done", "created_at": 1000.0,
            "user_id": uid, "source_type": "upload", "video": None,
        }
        self._seed_job("fine", [True], created_at=2000.0, user_id=uid)

        merged, sessions = career.merge_user_events(uid)   # must not raise
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["job_id"], "fine")


class TestEventFilterHelpers(unittest.TestCase):

    def test_events_for_session_isolates_one_session(self):
        events = [{"session": 1, "x": "a"}, {"session": 2, "x": "b"}, {"session": 1, "x": "c"}]
        self.assertEqual(career.events_for_session(events, 1), [events[0], events[2]])
        self.assertEqual(career.events_for_session(events, 2), [events[1]])
        self.assertEqual(career.events_for_session(events, 3), [])

    def test_events_through_session_is_a_growing_window(self):
        events = [{"session": 1}, {"session": 2}, {"session": 3}]
        self.assertEqual(len(career.events_through_session(events, 1)), 1)
        self.assertEqual(len(career.events_through_session(events, 2)), 2)
        self.assertEqual(len(career.events_through_session(events, 3)), 3)


class TestMatchDurations(_CareerJobSeedingMixin, unittest.TestCase):
    """backend/career.py's match_durations() - the /career/matches
    counterpart to job_matches_summary()'s per-job duration merge (see
    backend/main.py). Shares _CareerJobSeedingMixin with TestCareerMerge
    (temp JOBS_DIR, local-mode skip, _seed_job) without inheriting or
    re-running any of that class's own test_* methods."""

    def test_single_job_durations_keyed_by_remapped_global_match(self):
        uid = "user-h"
        self._seed_job("job1", [True, False], created_at=1000.0, user_id=uid,
                        durations={1: 245.0, 2: 310.5})

        merged, _sessions = career.merge_user_events(uid)
        # confirm what global numbers this job's local matches 1/2 actually
        # got remapped to, rather than assuming they stay 1/2 unchanged.
        global_matches = sorted({e["match"] for e in merged if e.get("match") is not None})
        self.assertEqual(global_matches, [1, 2])

        durations = career.match_durations(uid)
        self.assertEqual(durations, {1: 245.0, 2: 310.5})

    def test_durations_remap_correctly_across_multiple_jobs(self):
        """The real point of this feature: job B's local match 1 must NOT
        collide with job A's local match 1 - each must land on its own
        correct GLOBAL match number, the same remap merge_user_events()
        itself performs."""
        uid = "user-i"
        self._seed_job("jobA", [True, True], created_at=1000.0, user_id=uid,
                        durations={1: 100.0, 2: 150.0})   # local 1,2 -> expect global 1,2
        self._seed_job("jobB", [False, False, False], created_at=2000.0, user_id=uid,
                        durations={1: 200.0, 2: 210.0, 3: 220.0})   # local 1,2,3 -> expect global 3,4,5

        durations = career.match_durations(uid)
        self.assertEqual(durations, {1: 100.0, 2: 150.0, 3: 200.0, 4: 210.0, 5: 220.0})

    def test_job_with_no_matches_csv_contributes_no_durations(self):
        """A Showdown-import job (or any job predating duration_seconds) has
        no matches.csv at all - its matches should simply be absent from the
        returned dict, not raise or report a fake 0."""
        uid = "user-j"
        self._seed_job("no-csv", [True], created_at=1000.0, user_id=uid)   # no durations= given

        durations = career.match_durations(uid)
        self.assertEqual(durations, {})

    def test_mixed_jobs_only_the_one_with_a_matches_csv_contributes(self):
        uid = "user-k"
        self._seed_job("no-csv", [True], created_at=1000.0, user_id=uid)                       # global match 1
        self._seed_job("has-csv", [True], created_at=2000.0, user_id=uid, durations={1: 99.0})  # global match 2

        durations = career.match_durations(uid)
        self.assertEqual(durations, {2: 99.0})

    def test_unparseable_row_is_skipped_not_a_crash(self):
        uid = "user-l"
        d = self._seed_job("bad-row", [True, True], created_at=1000.0, user_id=uid)
        import csv
        with open(os.path.join(d, "matches.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["match", "duration_seconds"])
            w.writerow(["1", "not-a-number"])   # unparseable - must be skipped, not crash
            w.writerow(["2", "88.0"])           # this one is fine and should still come through

        durations = career.match_durations(uid)   # must not raise
        self.assertEqual(durations, {2: 88.0})

    def test_no_completed_jobs_returns_empty_dict(self):
        self.assertEqual(career.match_durations("nobody-has-uploaded-yet"), {})

    def test_scoped_to_one_user_only(self):
        self._seed_job("mine", [True], created_at=1000.0, user_id="user-m", durations={1: 42.0})
        self._seed_job("theirs", [True], created_at=1000.0, user_id="someone-else", durations={1: 999.0})

        durations = career.match_durations("user-m")
        self.assertEqual(durations, {1: 42.0})


class TestCreatedAtKey(unittest.TestCase):
    """created_at is a float in local dev mode, an ISO-8601 string from real
    Supabase (a timestamptz column) - _created_at_key must sort both shapes
    the same way, since a real deployment could have a mix if local-mode
    jobs were ever created before Supabase was configured."""

    def test_float_passes_through(self):
        self.assertEqual(career._created_at_key(1234.5), 1234.5)

    def test_none_sorts_first(self):
        self.assertEqual(career._created_at_key(None), 0.0)

    def test_iso_string_with_z_suffix(self):
        # 2025-01-01T00:00:00Z is a real, known instant - just check it parses
        # to a sane positive number, not the exact epoch math (leap seconds/
        # timezone library differences aren't the point of this test).
        self.assertGreater(career._created_at_key("2025-01-01T00:00:00Z"), 0)

    def test_iso_string_orders_correctly_relative_to_float(self):
        earlier = career._created_at_key("2020-01-01T00:00:00Z")
        later = career._created_at_key("2030-01-01T00:00:00Z")
        self.assertLess(earlier, later)

    def test_unparseable_string_falls_back_to_zero(self):
        self.assertEqual(career._created_at_key("not-a-date"), 0.0)


class TestSkillScoreTrend(unittest.TestCase):

    def test_shows_improvement_between_a_losing_and_winning_session(self):
        merged = []
        sessions = [
            {"session": 1, "job_id": "job1", "created_at": 1000.0, "matches_in_session": 3},
            {"session": 2, "job_id": "job2", "created_at": 2000.0, "matches_in_session": 3},
        ]
        for i, won in enumerate([False, False, True], start=1):
            for e in _team_preview_and_result(i, won):
                e["session"] = 1
                e["source_job_id"] = "job1"
                merged.append(e)
        for i, won in enumerate([True, True, True], start=4):
            for e in _team_preview_and_result(i, won):
                e["session"] = 2
                e["source_job_id"] = "job2"
                merged.append(e)

        trend = career.compute_skill_score_trend(merged, sessions)
        self.assertEqual(len(trend), 2)
        # session 1 alone: 1-2 record; session 2 alone: 3-0 - per_session should
        # show session 2 scoring meaningfully higher than session 1 (the real
        # "did I improve" signal this whole feature exists to provide).
        self.assertLess(trend[0]["per_session"]["overall"], trend[1]["per_session"]["overall"])

    def test_cumulative_differs_from_per_session_by_session_two(self):
        merged = []
        sessions = [
            {"session": 1, "job_id": "job1", "created_at": 1000.0, "matches_in_session": 2},
            {"session": 2, "job_id": "job2", "created_at": 2000.0, "matches_in_session": 2},
        ]
        for i, won in enumerate([False, False], start=1):
            for e in _team_preview_and_result(i, won):
                e["session"] = 1
                merged.append(e)
        for i, won in enumerate([True, True], start=3):
            for e in _team_preview_and_result(i, won):
                e["session"] = 2
                merged.append(e)

        trend = career.compute_skill_score_trend(merged, sessions)
        # session 1: cumulative == per_session (nothing came before it)
        self.assertEqual(trend[0]["per_session"]["overall"], trend[0]["cumulative"]["overall"])
        # session 2: cumulative blends both sessions, per_session is session 2 ALONE -
        # with a 0-2 session followed by a 2-0 session, these must differ.
        self.assertNotEqual(trend[1]["per_session"]["overall"], trend[1]["cumulative"]["overall"])

    def test_empty_sessions_list_returns_empty_trend(self):
        self.assertEqual(career.compute_skill_score_trend([], []), [])


if __name__ == "__main__":
    unittest.main()
