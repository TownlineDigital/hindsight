"""
Tests for backend/api_keys.py - long-lived, per-user API keys for external
clients (the planned Pokemon Showdown browser extension) that can't hold a
short-lived Supabase session - and for backend/auth.py's current_user()
accepting them as an alternative to a Supabase JWT. See api_keys.py's own
module docstring for the full design, especially why only a SHA-256 hash of
each key is ever stored, never the plaintext.

If `fastapi`/`supabase` aren't installed in this environment, minimal stubs
are injected first (same pattern as tests/test_coaching.py) - these tests
only exercise local-dev-mode logic (module-level dicts), never anything from
those real packages.

Run: py -m unittest tests.test_api_keys -v   (from poc-starter/)
"""

import os
import sys
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

from backend import api_keys                    # noqa: E402
from backend import audit                        # noqa: E402
from backend import auth as auth_module         # noqa: E402


class _LocalModeGuard(unittest.TestCase):
    """Shared setUp: skip entirely against a real configured Supabase
    project (same rationale as test_coaching.py's identical guard), and
    reset the in-memory dict api_keys.py uses so tests never leak state
    into one another."""

    @classmethod
    def setUpClass(cls):
        if auth_module.configured():
            raise unittest.SkipTest("Supabase IS configured in this environment - "
                                     "local-mode tests don't apply here.")

    def setUp(self):
        api_keys._LOCAL_API_KEYS.clear()


class TestLooksLikeApiKey(unittest.TestCase):
    def test_vgc_prefixed_token_is_recognized(self):
        self.assertTrue(api_keys.looks_like_api_key("vgc_abc123"))

    def test_supabase_style_jwt_is_not_recognized(self):
        # real Supabase JWTs are three dot-separated base64 segments and
        # never start with the vgc_ prefix - this is the cheap check
        # auth.current_user() relies on to skip a wasted network call.
        self.assertFalse(api_keys.looks_like_api_key("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.abc"))


class TestCreateListRevoke(_LocalModeGuard):
    def test_create_returns_plaintext_key_exactly_once(self):
        result = api_keys.create_api_key("user-1", label="Showdown extension")
        self.assertTrue(result["key"].startswith("vgc_"))
        self.assertEqual(result["label"], "Showdown extension")
        self.assertEqual(result["key_prefix"], result["key"][:12])

    def test_only_a_hash_is_ever_stored_not_the_plaintext(self):
        result = api_keys.create_api_key("user-1")
        stored = api_keys._LOCAL_API_KEYS[result["key_hash"]]
        self.assertNotIn("key", stored)
        self.assertNotEqual(stored["key_hash"], result["key"])
        self.assertEqual(stored["key_hash"], api_keys._hash(result["key"]))

    def test_list_api_keys_never_includes_key_hash_or_plaintext(self):
        api_keys.create_api_key("user-1", label="a")
        rows = api_keys.list_api_keys("user-1")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("key_hash", rows[0])
        self.assertNotIn("key", rows[0])
        self.assertEqual(rows[0]["label"], "a")

    def test_list_api_keys_only_returns_this_users_own(self):
        api_keys.create_api_key("user-1", label="mine")
        api_keys.create_api_key("user-2", label="not mine")
        mine = api_keys.list_api_keys("user-1")
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["label"], "mine")

    def test_revoke_disables_the_key(self):
        result = api_keys.create_api_key("user-1")
        self.assertTrue(api_keys.revoke_api_key("user-1", result["id"]))
        rows = api_keys.list_api_keys("user-1")
        self.assertIsNotNone(rows[0]["revoked_at"])

    def test_cannot_revoke_someone_elses_key(self):
        result = api_keys.create_api_key("user-1")
        self.assertFalse(api_keys.revoke_api_key("someone-else", result["id"]))
        rows = api_keys.list_api_keys("user-1")
        self.assertIsNone(rows[0]["revoked_at"])

    def test_revoke_unknown_key_id_returns_false(self):
        self.assertFalse(api_keys.revoke_api_key("user-1", "not-a-real-id"))


class TestResolveApiKey(_LocalModeGuard):
    def test_valid_key_resolves_to_its_owner(self):
        result = api_keys.create_api_key("user-1")
        resolved = api_keys.resolve_api_key(result["key"])
        self.assertEqual(resolved, {"id": "user-1", "email": None})

    def test_unknown_key_resolves_to_none(self):
        self.assertIsNone(api_keys.resolve_api_key("vgc_this-was-never-created"))

    def test_revoked_key_no_longer_resolves(self):
        result = api_keys.create_api_key("user-1")
        api_keys.revoke_api_key("user-1", result["id"])
        self.assertIsNone(api_keys.resolve_api_key(result["key"]))

    def test_resolve_updates_last_used_at(self):
        result = api_keys.create_api_key("user-1")
        self.assertIsNone(api_keys.list_api_keys("user-1")[0]["last_used_at"])
        api_keys.resolve_api_key(result["key"])
        self.assertIsNotNone(api_keys.list_api_keys("user-1")[0]["last_used_at"])


class TestApiKeyAuditLogging(_LocalModeGuard):
    """Mirrors test_coaching.py's TestCoachingAuditLogging - create/revoke
    should also write through to the internal audit log (backend/audit.py)."""

    def setUp(self):
        super().setUp()
        import shutil
        import tempfile
        from pathlib import Path
        self._tmp = tempfile.mkdtemp()
        self._orig_log_path = audit.LOG_PATH
        audit.LOG_PATH = Path(self._tmp) / "audit_log.jsonl"
        self.addCleanup(lambda: (audit.__setattr__("LOG_PATH", self._orig_log_path),
                                  shutil.rmtree(self._tmp, ignore_errors=True)))

    def _event_types(self):
        return [e["event_type"] for e in audit.read_local()]

    def test_create_is_logged(self):
        result = api_keys.create_api_key("user-1", label="Showdown extension")
        self.assertIn("api_key_created", self._event_types())
        entry = next(e for e in audit.read_local() if e["event_type"] == "api_key_created")
        self.assertEqual(entry["payload"]["user_id"], "user-1")
        self.assertEqual(entry["payload"]["key_id"], result["id"])
        self.assertEqual(entry["payload"]["label"], "Showdown extension")

    def test_revoke_is_logged_only_on_success(self):
        result = api_keys.create_api_key("user-1")
        api_keys.revoke_api_key("someone-else", result["id"])
        self.assertNotIn("api_key_revoked", self._event_types())
        api_keys.revoke_api_key("user-1", result["id"])
        self.assertIn("api_key_revoked", self._event_types())


class TestCurrentUserAcceptsApiKeys(unittest.TestCase):
    """backend/auth.py's current_user() - the actual FastAPI dependency
    every endpoint uses - should accept a valid Bearer API key exactly like
    it accepts a valid Supabase session JWT. These tests force `configured`
    to look True (without a real Supabase client) by monkeypatching, since
    current_user()'s API-key branch is checked BEFORE the Supabase JWT
    branch and never touches get_service_client() for a vgc_-prefixed
    token."""

    def setUp(self):
        api_keys._LOCAL_API_KEYS.clear()
        self._orig_configured = auth_module.configured
        auth_module.configured = lambda: True   # pretend Supabase is set up
        self.addCleanup(lambda: setattr(auth_module, "configured", self._orig_configured))
        # api_keys.py's own configured() reference must also report True,
        # since resolve_api_key() branches on it to pick the storage backend
        # - but we still want it to fall back to the in-memory dict rather
        # than actually touching Supabase, so patch api_keys.configured too
        # and pre-seed a "Supabase-shaped" row directly into the in-memory
        # dict as a stand-in.
        self._orig_api_keys_configured = api_keys.configured
        api_keys.configured = lambda: False   # keep api_keys.py itself in local-dict mode
        self.addCleanup(lambda: setattr(api_keys, "configured", self._orig_api_keys_configured))

    def test_valid_api_key_resolves_current_user(self):
        result = api_keys.create_api_key("user-1")
        user = auth_module.current_user(authorization=f"Bearer {result['key']}")
        self.assertEqual(user["id"], "user-1")

    def test_revoked_api_key_is_rejected(self):
        result = api_keys.create_api_key("user-1")
        api_keys.revoke_api_key("user-1", result["id"])
        with self.assertRaises(_StubHTTPException) as ctx:
            auth_module.current_user(authorization=f"Bearer {result['key']}")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_bogus_api_key_shaped_token_is_rejected(self):
        with self.assertRaises(_StubHTTPException) as ctx:
            auth_module.current_user(authorization="Bearer vgc_this-was-never-issued")
        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
