"""
Tests for backend/coaching.py - player-generated shareable links, the
persistent coach/student roster they create, and the notes a coach can leave
for a student. See that module's own docstring for the full privacy model
this is testing: nothing is visible to anyone without a valid, non-revoked,
non-expired token the PLAYER themselves generated.

If `fastapi`/`supabase` aren't installed in this environment, minimal stubs
are injected first (same pattern as tests/test_career.py) - these tests only
exercise local-dev-mode logic (module-level dicts), never anything from
those real packages.

Run: py -m unittest tests.test_coaching -v   (from poc-starter/)
"""

import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path


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

from backend import audit                       # noqa: E402
from backend import auth as auth_module        # noqa: E402
from backend import coaching                    # noqa: E402
from backend import jobs as jobs_module         # noqa: E402


class _LocalModeGuard(unittest.TestCase):
    """Shared setUp/tearDown: skip entirely against a real configured
    Supabase project (same rationale as test_career.py's identical guard),
    and reset every in-memory dict coaching.py uses so tests never leak
    state into one another."""

    @classmethod
    def setUpClass(cls):
        if auth_module.configured():
            raise unittest.SkipTest("Supabase IS configured in this environment - "
                                     "local-mode tests don't apply here.")

    def setUp(self):
        coaching._LOCAL_SHARE_LINKS.clear()
        coaching._LOCAL_COACH_STUDENTS.clear()
        coaching._LOCAL_COACH_NOTES.clear()


class TestShareLinks(_LocalModeGuard):

    def test_create_then_resolve_round_trips_owner_and_label(self):
        link = coaching.create_share_link("player-1", label="for Coach Sarah")
        resolved = coaching.resolve_share_link(link["token"])
        self.assertEqual(resolved, {"user_id": "player-1", "label": "for Coach Sarah"})

    def test_unknown_token_resolves_to_none(self):
        self.assertIsNone(coaching.resolve_share_link("this-token-was-never-created"))

    def test_revoked_link_no_longer_resolves(self):
        link = coaching.create_share_link("player-1")
        self.assertTrue(coaching.revoke_share_link("player-1", link["token"]))
        self.assertIsNone(coaching.resolve_share_link(link["token"]))

    def test_cannot_revoke_someone_elses_link(self):
        link = coaching.create_share_link("player-1")
        self.assertFalse(coaching.revoke_share_link("someone-else", link["token"]))
        # still valid - the revoke attempt from the wrong owner had no effect
        self.assertIsNotNone(coaching.resolve_share_link(link["token"]))

    def test_no_expiration_by_default(self):
        link = coaching.create_share_link("player-1")
        self.assertIsNone(link["expires_at"])
        self.assertIsNotNone(coaching.resolve_share_link(link["token"]))

    def test_expired_link_no_longer_resolves(self):
        # expires_in_days=-1 is a test-only trick (a real caller would never
        # pass a negative value) to land expires_at in the past without
        # needing to mock time.time() - create_share_link's own arithmetic
        # (now + expires_in_days * 86400) makes this land exactly where a
        # real link's 1-day expiration would land the moment it lapses.
        link = coaching.create_share_link("player-1", expires_in_days=-1)
        self.assertIsNone(coaching.resolve_share_link(link["token"]))

    def test_future_expiration_still_resolves(self):
        link = coaching.create_share_link("player-1", expires_in_days=30)
        self.assertIsNotNone(coaching.resolve_share_link(link["token"]))

    def test_list_share_links_only_returns_this_players_own(self):
        coaching.create_share_link("player-1", label="a")
        coaching.create_share_link("player-1", label="b")
        coaching.create_share_link("player-2", label="c")
        mine = coaching.list_share_links("player-1")
        self.assertEqual(len(mine), 2)
        self.assertEqual({r["label"] for r in mine}, {"a", "b"})

    def test_touch_share_link_sets_last_viewed_at(self):
        link = coaching.create_share_link("player-1")
        self.assertIsNone(link["last_viewed_at"])
        coaching.touch_share_link(link["token"])
        updated = [r for r in coaching.list_share_links("player-1") if r["token"] == link["token"]][0]
        self.assertIsNotNone(updated["last_viewed_at"])


class TestStudentRoster(_LocalModeGuard):

    def test_add_student_via_valid_token(self):
        link = coaching.create_share_link("player-1", label="Practice partner")
        result = coaching.add_student("coach-1", link["token"])
        self.assertIsNotNone(result)
        self.assertEqual(result["player_user_id"], "player-1")
        self.assertEqual(result["coach_label"], "Practice partner")   # defaults to the link's own label

    def test_add_student_defaults_label_when_link_has_none(self):
        link = coaching.create_share_link("player-1")   # no label
        result = coaching.add_student("coach-1", link["token"])
        self.assertTrue(result["coach_label"].startswith("Player "))

    def test_add_student_with_invalid_token_returns_none(self):
        self.assertIsNone(coaching.add_student("coach-1", "not-a-real-token"))

    def test_add_student_is_idempotent(self):
        link = coaching.create_share_link("player-1")
        first = coaching.add_student("coach-1", link["token"])
        coaching.rename_student("coach-1", "player-1", "My custom nickname")
        second = coaching.add_student("coach-1", link["token"])
        # redeeming again returns the EXISTING row (with the rename intact),
        # not a fresh one that would have clobbered the coach's own label
        self.assertEqual(second["coach_label"], "My custom nickname")
        self.assertEqual(first["id"], second["id"])

    def test_list_students_only_this_coachs_roster(self):
        link_a = coaching.create_share_link("player-a")
        link_b = coaching.create_share_link("player-b")
        coaching.add_student("coach-1", link_a["token"])
        coaching.add_student("coach-2", link_b["token"])
        roster = coaching.list_students("coach-1")
        self.assertEqual(len(roster), 1)
        self.assertEqual(roster[0]["player_user_id"], "player-a")

    def test_rename_student(self):
        link = coaching.create_share_link("player-1")
        coaching.add_student("coach-1", link["token"])
        self.assertTrue(coaching.rename_student("coach-1", "player-1", "Renamed"))
        self.assertEqual(coaching.get_student_link("coach-1", "player-1")["coach_label"], "Renamed")

    def test_rename_nonexistent_student_returns_false(self):
        self.assertFalse(coaching.rename_student("coach-1", "no-such-player", "x"))

    def test_remove_student_revokes_get_student_link(self):
        link = coaching.create_share_link("player-1")
        coaching.add_student("coach-1", link["token"])
        self.assertTrue(coaching.remove_student("coach-1", "player-1"))
        self.assertIsNone(coaching.get_student_link("coach-1", "player-1"))

    def test_removing_a_student_does_not_revoke_the_underlying_share_link(self):
        """Two independently-revocable layers, by design (see
        remove_student's own docstring): removing from a roster is scoped
        to ONE coach's relationship, not the player's own link."""
        link = coaching.create_share_link("player-1")
        coaching.add_student("coach-1", link["token"])
        coaching.remove_student("coach-1", "player-1")
        self.assertIsNotNone(coaching.resolve_share_link(link["token"]))


class TestCoachNotes(_LocalModeGuard):

    def setUp(self):
        super().setUp()
        link = coaching.create_share_link("player-1")
        coaching.add_student("coach-1", link["token"])

    def test_add_and_list_note(self):
        coaching.add_note("coach-1", "player-1", "Work on switch timing.",
                          coach_email="coach@example.com", category="skill_focus")
        notes = coaching.list_notes_by_coach_for_student("coach-1", "player-1")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["text"], "Work on switch timing.")
        self.assertEqual(notes[0]["category"], "skill_focus")
        self.assertEqual(notes[0]["coach_email"], "coach@example.com")

    def test_player_sees_notes_from_every_coach(self):
        link2 = coaching.create_share_link("player-1")
        coaching.add_student("coach-2", link2["token"])
        coaching.add_note("coach-1", "player-1", "Note from coach 1", coach_email="c1@x.com")
        coaching.add_note("coach-2", "player-1", "Note from coach 2", coach_email="c2@x.com")
        about_me = coaching.list_notes_about_player("player-1")
        self.assertEqual({n["text"] for n in about_me}, {"Note from coach 1", "Note from coach 2"})

    def test_player_still_sees_notes_after_being_removed_from_roster(self):
        coaching.add_note("coach-1", "player-1", "A note that should persist",
                          coach_email="coach@example.com")
        coaching.remove_student("coach-1", "player-1")
        about_me = coaching.list_notes_about_player("player-1")
        self.assertEqual(len(about_me), 1)

    def test_update_note_is_scoped_to_the_writing_coach(self):
        note = coaching.add_note("coach-1", "player-1", "Original", coach_email="c1@x.com")
        self.assertIsNone(coaching.update_note("coach-2", note["id"], text="Hijacked"))
        result = coaching.update_note("coach-1", note["id"], text="Edited")
        self.assertEqual(result["text"], "Edited")

    def test_delete_note_is_scoped_to_the_writing_coach(self):
        note = coaching.add_note("coach-1", "player-1", "To delete", coach_email="c1@x.com")
        self.assertFalse(coaching.delete_note("coach-2", note["id"]))
        self.assertTrue(coaching.delete_note("coach-1", note["id"]))
        self.assertEqual(coaching.list_notes_by_coach_for_student("coach-1", "player-1"), [])


def _team_preview_and_result(match_n, won):
    """Minimal but realistic 3-event match, same shape test_career.py's own
    helper uses - just enough for compute_playstyle_profile's downstream
    analytics functions to compute something real."""
    return [
        {"event": "team_preview", "match": match_n,
         "player_lead": "Rotom, Incineroar",
         "player_brought": "Rotom, Incineroar, Whimsicott, Rillaboom"},
        {"event": "pokemon_fainted", "match": match_n,
         "actor": "opponent" if won else "player", "timestamp": 10},
        {"event": "battle_end", "match": match_n, "winner": "player" if won else "opponent"},
    ]


class TestComputePlaystyleProfile(_LocalModeGuard):
    """compute_playstyle_profile() is the AGGREGATE-ONLY payload both the
    public coach-view and the authenticated per-student profile endpoint
    return - built entirely from already-tested career/analytics functions
    (see coaching.py's own docstring for why). These tests seed a real job
    folder (same technique test_career.py uses) to confirm the composition
    actually works end-to-end, not just that each piece works in isolation."""

    def setUp(self):
        super().setUp()
        self._tmp_jobs_dir = tempfile.mkdtemp()
        self._orig_jobs_dir = jobs_module.JOBS_DIR
        jobs_module.JOBS_DIR = type(self._orig_jobs_dir)(self._tmp_jobs_dir)
        jobs_module._LOCAL_JOBS.clear()
        jobs_module._local_discovered = True
        self._job_dir = tempfile.mkdtemp()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        jobs_module.JOBS_DIR = self._orig_jobs_dir
        shutil.rmtree(self._tmp_jobs_dir, ignore_errors=True)
        shutil.rmtree(self._job_dir, ignore_errors=True)

    def _seed_job(self, job_id, user_id, win_pattern):
        events = []
        for i, won in enumerate(win_pattern, start=1):
            events.extend(_team_preview_and_result(i, won))
        with open(os.path.join(self._job_dir, "events.json"), "w", encoding="utf-8") as f:
            json.dump(events, f)
        jobs_module._LOCAL_JOBS[job_id] = {
            "job_id": job_id, "dir": self._job_dir, "status": "done", "created_at": 1000.0,
            "user_id": user_id, "source_type": "upload", "video": None,
        }

    def test_profile_shape_and_content(self):
        self._seed_job("job1", "player-1", [True, True, False])
        profile = coaching.compute_playstyle_profile("player-1")
        for key in ("record", "report", "skill_scores", "skill_score_trend",
                    "sessions_count", "generated_at"):
            self.assertIn(key, profile)
        self.assertEqual(profile["record"]["wins"], 2)
        self.assertEqual(profile["record"]["losses"], 1)
        self.assertEqual(profile["sessions_count"], 1)

    def test_profile_never_includes_raw_events_or_match_list(self):
        """The explicit scope decision this feature was built to: aggregate
        only, never a per-match browser or raw event stream - see
        compute_playstyle_profile's own docstring."""
        self._seed_job("job1", "player-1", [True])
        profile = coaching.compute_playstyle_profile("player-1")
        self.assertNotIn("events", profile)
        self.assertNotIn("matches", profile)
        self.assertNotIn("decision_windows", profile)

    def test_no_completed_jobs_still_returns_a_well_formed_profile(self):
        profile = coaching.compute_playstyle_profile("player-with-nothing-uploaded")
        self.assertEqual(profile["sessions_count"], 0)
        self.assertEqual(profile["record"]["matches"], 0)
        self.assertIsNone(profile["skill_scores"]["scores"])


class TestCoachingAuditLogging(_LocalModeGuard):
    """Every coach-sharing lifecycle action (link created/revoked/viewed,
    student added/removed, note added) should also write through to the
    internal audit log (backend/audit.py) - this is the "how are people
    actually using this feature" signal the app is built to capture, not
    just the durable business-data rows in the in-memory dicts. Redirects
    audit.LOG_PATH to a throwaway temp file (same technique test_audit.py's
    own TestAuditLocalMode uses) so these tests never touch the real
    audit_log.jsonl at the project root."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp()
        self._orig_log_path = audit.LOG_PATH
        audit.LOG_PATH = Path(self._tmp) / "audit_log.jsonl"
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        audit.LOG_PATH = self._orig_log_path
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _event_types(self):
        return [e["event_type"] for e in audit.read_local()]

    def test_create_share_link_is_logged(self):
        link = coaching.create_share_link("player-1", label="for Coach Sarah", expires_in_days=30)
        entries = audit.read_local()
        self.assertIn("share_link_created", self._event_types())
        entry = next(e for e in entries if e["event_type"] == "share_link_created")
        self.assertEqual(entry["payload"]["user_id"], "player-1")
        self.assertEqual(entry["payload"]["token"], link["token"])
        self.assertEqual(entry["payload"]["label"], "for Coach Sarah")

    def test_revoke_share_link_is_logged_only_on_success(self):
        link = coaching.create_share_link("player-1")
        # a failed revoke attempt (wrong owner) should NOT log anything
        coaching.revoke_share_link("someone-else", link["token"])
        self.assertNotIn("share_link_revoked", self._event_types())
        coaching.revoke_share_link("player-1", link["token"])
        self.assertIn("share_link_revoked", self._event_types())

    def test_touch_share_link_is_logged(self):
        link = coaching.create_share_link("player-1")
        coaching.touch_share_link(link["token"])
        self.assertIn("share_link_viewed", self._event_types())

    def test_add_student_is_logged_once_not_on_idempotent_redeem(self):
        link = coaching.create_share_link("player-1")
        coaching.add_student("coach-1", link["token"])
        coaching.add_student("coach-1", link["token"])   # idempotent redeem
        self.assertEqual(self._event_types().count("student_added"), 1)

    def test_remove_student_is_logged_only_on_success(self):
        link = coaching.create_share_link("player-1")
        coaching.add_student("coach-1", link["token"])
        coaching.remove_student("coach-2", "player-1")   # not this coach's student - no-op
        self.assertNotIn("student_removed", self._event_types())
        coaching.remove_student("coach-1", "player-1")
        self.assertIn("student_removed", self._event_types())

    def test_add_note_is_logged_with_category(self):
        link = coaching.create_share_link("player-1")
        coaching.add_student("coach-1", link["token"])
        coaching.add_note("coach-1", "player-1", "Work on switch timing.",
                          coach_email="coach@example.com", category="skill_focus")
        entries = audit.read_local()
        entry = next(e for e in entries if e["event_type"] == "coach_note_added")
        self.assertEqual(entry["payload"]["category"], "skill_focus")
        self.assertEqual(entry["payload"]["coach_user_id"], "coach-1")
        self.assertEqual(entry["payload"]["player_user_id"], "player-1")


if __name__ == "__main__":
    unittest.main()
