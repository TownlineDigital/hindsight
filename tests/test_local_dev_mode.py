"""
Regression tests for local dev mode (backend/auth.py + backend/jobs.py) -
what lets the app run and serve the dashboard with ZERO Supabase setup,
falling back to a single fixed local user and an in-memory job store instead
of requiring real accounts. This is the mechanism that unblocks checking the
frontend rework before doing the (much bigger, still-unverified) Supabase
setup - see backend/README_BACKEND.md "Accounts".

If `fastapi`/`supabase` aren't installed in this environment, minimal stubs
are injected into sys.modules first - this test only exercises the LOCAL-MODE
code paths, which never call anything from those real packages, so a stub is
enough to prove the logic itself is correct without needing either package
actually installed.

Run: py -m unittest tests.test_local_dev_mode -v   (from poc-starter/)
"""

import os
import shutil
import sys
import tempfile
import types
import unittest


def _ensure_stub(name, attrs):
    """Only stub a module if it's genuinely missing - if the real package IS
    installed, use it for real instead of shadowing it."""
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
from backend import jobs as jobs_module   # noqa: E402


class TestLocalDevMode(unittest.TestCase):
    """These only make sense when Supabase genuinely isn't configured in this
    process's environment - skip rather than false-fail if SUPABASE_URL/
    SUPABASE_SERVICE_ROLE_KEY happen to be set (e.g. running against a real
    project already)."""

    @classmethod
    def setUpClass(cls):
        if auth_module.configured():
            raise unittest.SkipTest("Supabase IS configured in this environment - "
                                     "local-mode tests don't apply here.")
        # Isolate from the real jobs/ folder (which may have real demo data)
        # by pointing both modules at a scratch directory for this test class.
        cls._tmp = tempfile.mkdtemp()
        cls._orig_jobs_dir = jobs_module.JOBS_DIR
        jobs_module.JOBS_DIR = type(cls._orig_jobs_dir)(cls._tmp)
        jobs_module._LOCAL_JOBS.clear()
        jobs_module._local_discovered = False

    @classmethod
    def tearDownClass(cls):
        jobs_module.JOBS_DIR = cls._orig_jobs_dir
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_current_user_returns_local_user_without_a_token(self):
        user = auth_module.current_user(authorization="")
        self.assertEqual(user, auth_module.LOCAL_USER)

    def test_create_get_update_list_job_round_trip(self):
        user_id = auth_module.LOCAL_USER["id"]
        job = jobs_module.create_job(user_id=user_id, game="pokemon", mode="doubles",
                                      source_type="url", url="https://example.com/vod")
        self.assertEqual(job["user_id"], user_id)
        self.assertEqual(job["status"], "queued")

        fetched = jobs_module.get_job(job["job_id"], user_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["job_id"], job["job_id"])

        updated = jobs_module.update_job(job["job_id"], user_id, status="running", step="structure_pass")
        self.assertEqual(updated["status"], "running")

        all_jobs = jobs_module.list_jobs(user_id)
        self.assertIn(job["job_id"], [j["job_id"] for j in all_jobs])

    def test_unknown_job_id_returns_none_not_a_crash(self):
        self.assertIsNone(jobs_module.get_job("does-not-exist", auth_module.LOCAL_USER["id"]))


if __name__ == "__main__":
    unittest.main()
