"""
Regression test for a real bug found while testing the dashboard end-to-end:
backend/pipeline.py's _run() shells out to scripts like analyze_matches.py
with subprocess.run(..., capture_output=True, text=True) - no explicit
encoding. Several scripts print emoji (analyze_matches.py's
"🚫 REJECTED illegal species..." lines, for one). That's fine when a script
is run directly in an interactive terminal (Windows' console layer handles
Unicode), but when its stdout/stderr are captured through a pipe instead,
Python falls back to the OS's legacy locale encoding (often cp1252 on
Windows), which can't represent an emoji - so the CHILD process itself
crashed with an unhandled UnicodeEncodeError the instant it tried to print
one. From the API's point of view this just looked like an ordinary script
failure (exit 1, a truncated traceback cut off mid-frame) - genuinely
confusing to track down, since the exact same command worked perfectly when
run by hand. Fixed by forcing UTF-8 on both ends: PYTHONIOENCODING/
PYTHONUTF8 in the child's environment, and encoding="utf-8" (errors=
"replace" as a last-resort safety net) on the subprocess.run() call itself.

Run: py -m unittest tests.test_pipeline_subprocess -v   (from poc-starter/)
"""

import os
import sys
import types
import unittest
from unittest.mock import patch


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


_ensure_stub("fastapi", {
    "Header": lambda default=None, **kw: default,
    "HTTPException": Exception,
})
_ensure_stub("supabase", {
    "Client": object,
    "create_client": lambda url, key: (_ for _ in ()).throw(
        RuntimeError("create_client() should never be called in local dev mode")),
})

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend import pipeline  # noqa: E402


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestRunForcesUtf8OnTheSubprocess(unittest.TestCase):
    def test_subprocess_run_gets_utf8_encoding_and_errors_replace(self):
        with patch.object(pipeline.subprocess, "run",
                           return_value=_FakeCompletedProcess()) as mock_run:
            pipeline._run("some_script.py", ["--flag", "value"], cwd=pipeline.BASE_DIR)

        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs.get("encoding"), "utf-8")
        self.assertEqual(kwargs.get("errors"), "replace")
        self.assertTrue(kwargs.get("text"))
        self.assertTrue(kwargs.get("capture_output"))

    def test_child_env_has_pythonioencoding_and_pythonutf8_set(self):
        """The encoding="utf-8" kwarg only fixes how the PARENT decodes what
        it gets back - the CHILD also needs to be told to open its own
        stdout/stderr as UTF-8, or it can still crash trying to print an
        emoji before a single byte even reaches the parent."""
        with patch.object(pipeline.subprocess, "run",
                           return_value=_FakeCompletedProcess()) as mock_run:
            pipeline._run("some_script.py", [], cwd=pipeline.BASE_DIR)

        _, kwargs = mock_run.call_args
        child_env = kwargs.get("env")
        self.assertIsNotNone(child_env, "env= must be passed so the child gets the override")
        self.assertEqual(child_env.get("PYTHONIOENCODING"), "utf-8")
        self.assertEqual(child_env.get("PYTHONUTF8"), "1")

    def test_child_env_still_inherits_the_rest_of_the_parent_environment(self):
        """Must not silently drop things like GEMINI_API_KEY or PATH by
        passing a bare env={...} instead of layering on top of os.environ -
        that would break the pipeline in a much worse, harder-to-diagnose
        way than the bug this fix addresses."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-123", "SOME_OTHER_VAR": "kept"}):
            with patch.object(pipeline.subprocess, "run",
                               return_value=_FakeCompletedProcess()) as mock_run:
                pipeline._run("some_script.py", [], cwd=pipeline.BASE_DIR)

            _, kwargs = mock_run.call_args
            child_env = kwargs.get("env")
            self.assertEqual(child_env.get("GEMINI_API_KEY"), "test-key-123")
            self.assertEqual(child_env.get("SOME_OTHER_VAR"), "kept")

    def test_still_raises_step_failed_on_nonzero_exit(self):
        with patch.object(pipeline.subprocess, "run",
                           return_value=_FakeCompletedProcess(returncode=1, stderr="boom")):
            with self.assertRaises(pipeline.StepFailed):
                pipeline._run("some_script.py", [], cwd=pipeline.BASE_DIR)

    def test_optional_step_swallows_the_failure(self):
        with patch.object(pipeline.subprocess, "run",
                           return_value=_FakeCompletedProcess(returncode=1, stderr="boom")):
            pipeline._run("some_script.py", [], cwd=pipeline.BASE_DIR, optional=True)  # must not raise


if __name__ == "__main__":
    unittest.main()
