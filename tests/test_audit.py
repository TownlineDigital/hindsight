"""
Tests for backend/audit.py - the internal (not user-facing) audit log that
records job lifecycle events and manual corrections, kept separately from
any single job's own folder so it survives even if that folder is ever
removed. See ARCHITECTURE_HANDOFF.md's data-retention note.

If `fastapi`/`supabase` aren't installed, minimal stubs are injected first
(same pattern as test_local_dev_mode.py) since backend/audit.py imports
backend/auth.py (lazily, inside record()), which imports fastapi/supabase.

Run: py -m unittest tests.test_audit -v   (from poc-starter/)
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

from backend import audit  # noqa: E402
from backend import auth as auth_module  # noqa: E402


class TestAuditLocalMode(unittest.TestCase):
    """Only meaningful when Supabase genuinely isn't configured in this
    process - skip rather than false-fail if real credentials happen to be
    set (mirrors test_local_dev_mode.py's own guard)."""

    @classmethod
    def setUpClass(cls):
        if auth_module.configured():
            raise unittest.SkipTest("Supabase IS configured in this environment - "
                                     "local-mode audit tests don't apply here.")

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig_log_path = audit.LOG_PATH
        audit.LOG_PATH = Path(self._tmp) / "audit_log.jsonl"

    def tearDown(self):
        audit.LOG_PATH = self._orig_log_path
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_record_appends_a_json_line_with_the_right_shape(self):
        audit.record("job_created", job_id="abc123", user_id="u1", source_type="upload")
        entries = audit.read_local()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["event_type"], "job_created")
        self.assertIn("id", entry)
        self.assertIn("created_at", entry)
        self.assertEqual(entry["payload"], {"job_id": "abc123", "user_id": "u1", "source_type": "upload"})

    def test_multiple_records_append_in_order(self):
        audit.record("job_created", job_id="j1")
        audit.record("job_step", job_id="j1", step="compose_schema")
        audit.record("job_completed", job_id="j1")
        entries = audit.read_local()
        self.assertEqual([e["event_type"] for e in entries],
                         ["job_created", "job_step", "job_completed"])

    def test_read_local_respects_limit(self):
        for i in range(5):
            audit.record("job_step", step=str(i))
        entries = audit.read_local(limit=2)
        self.assertEqual(len(entries), 2)
        # the LAST 2 written, not the first 2
        self.assertEqual(entries[-1]["payload"]["step"], "4")

    def test_read_local_with_no_file_yet_returns_empty_list(self):
        self.assertEqual(audit.read_local(), [])

    def test_read_local_skips_corrupted_lines_without_crashing(self):
        audit.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(audit.LOG_PATH, "w", encoding="utf-8") as f:
            f.write("not valid json\n")
            f.write(json.dumps({"id": "x", "event_type": "job_created", "created_at": 1.0, "payload": {}}) + "\n")
        entries = audit.read_local()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["event_type"], "job_created")

    def test_record_never_raises_even_if_local_write_fails(self):
        """Points LOG_PATH somewhere writing genuinely can't succeed (a
        directory, not a file) - record() must swallow the error, not
        propagate it. An internal-logging failure should never be the
        reason a real user-facing job fails."""
        bad_dir = Path(self._tmp) / "not_a_file"
        bad_dir.mkdir()
        audit.LOG_PATH = bad_dir   # writing to a directory path will raise IsADirectoryError
        try:
            audit.record("job_created", job_id="whatever")
        except Exception as e:
            self.fail(f"record() must not raise, got: {e!r}")


if __name__ == "__main__":
    unittest.main()
