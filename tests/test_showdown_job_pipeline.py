"""
Tests for the Showdown-replay job path added to backend/pipeline.py and
backend/jobs.py - what lets POST /jobs accept source_type="showdown" (an
uploaded replay file, several replay files, or one/several replay URLs)
instead of only video. See ARCHITECTURE_HANDOFF.md section 2a/2b.

These test the ORCHESTRATION logic (which showdown_import.py CLI args get
built from what's sitting in the job dir, and the per-source-type step
count) with a fake _run() that just records calls instead of actually
shelling out to showdown_import.py - the parsing logic itself is already
covered end-to-end against a real replay in test_showdown_import.py.

If `fastapi`/`supabase` aren't installed, minimal stubs are injected first
(same pattern as test_local_dev_mode.py) since backend/pipeline.py imports
cleanly without either, but backend/jobs.py (imported for the total_steps_for
+ create_job round-trip test) pulls in backend/auth.py, which does import
fastapi.

Run: py -m unittest tests.test_showdown_job_pipeline -v   (from poc-starter/)
"""

import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
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

from backend import pipeline  # noqa: E402


class TestTotalStepsFor(unittest.TestCase):
    def test_video_source_types_use_the_full_video_step_list(self):
        for source_type in ("url", "upload", "seed"):
            with self.subTest(source_type=source_type):
                self.assertEqual(pipeline.total_steps_for(source_type), len(pipeline.STEPS))

    def test_showdown_uses_the_shorter_showdown_step_list(self):
        """No video/AI steps at all - see STEPS_SHOWDOWN's comment for why."""
        self.assertEqual(pipeline.total_steps_for("showdown"), len(pipeline.STEPS_SHOWDOWN))
        self.assertLess(len(pipeline.STEPS_SHOWDOWN), len(pipeline.STEPS))


class TestRunShowdownPipeline(unittest.TestCase):
    """Verifies run_showdown_pipeline() picks the right showdown_import.py
    CLI invocation based on what's actually sitting in the job dir, without
    ever really shelling out - _run is patched to just record its args."""

    def setUp(self):
        self.job_dir = Path(tempfile.mkdtemp())
        self.calls = []
        self.progress = []

    def tearDown(self):
        shutil.rmtree(self.job_dir, ignore_errors=True)

    def _fake_run(self, script, args, cwd, optional=False):
        self.calls.append((script, args))

    def _on_progress(self, step, index):
        self.progress.append((step, index))

    def test_uses_uploaded_replay_files_when_present(self):
        (self.job_dir / "replay0.html").write_text("dummy", encoding="utf-8")
        (self.job_dir / "replay1.json").write_text("dummy", encoding="utf-8")

        with patch.object(pipeline, "_run", side_effect=self._fake_run):
            pipeline.run_showdown_pipeline(self.job_dir, "pokemon", "doubles", "p1", self._on_progress)

        script, args = self.calls[0]
        self.assertEqual(script, "showdown_import.py")
        self.assertIn("--files", args)
        # both uploaded replay files should be passed, in sorted (replay0, replay1) order
        idx = args.index("--files")
        self.assertEqual(args[idx + 1], "replay0.html")
        self.assertEqual(args[idx + 2], "replay1.json")
        self.assertIn("p1", args)

    def test_uses_replay_urls_file_when_no_uploaded_files_present(self):
        (self.job_dir / "replay_urls.txt").write_text(
            "https://replay.pokemonshowdown.com/a\nhttps://replay.pokemonshowdown.com/b\n",
            encoding="utf-8")

        with patch.object(pipeline, "_run", side_effect=self._fake_run):
            pipeline.run_showdown_pipeline(self.job_dir, "pokemon", "doubles", "SomeUsername", self._on_progress)

        script, args = self.calls[0]
        self.assertEqual(script, "showdown_import.py")
        self.assertIn("--urls", args)
        idx = args.index("--urls")
        self.assertEqual(args[idx + 1], "https://replay.pokemonshowdown.com/a")
        self.assertEqual(args[idx + 2], "https://replay.pokemonshowdown.com/b")
        self.assertIn("SomeUsername", args)

    def test_replay_files_take_precedence_over_a_urls_file(self):
        """Shouldn't happen via the API (main.py's create_job only ever
        writes one or the other), but if both somehow exist, uploaded files
        win - matching showdown_import.py's own build_sources() precedence."""
        (self.job_dir / "replay0.html").write_text("dummy", encoding="utf-8")
        (self.job_dir / "replay_urls.txt").write_text("https://replay.pokemonshowdown.com/a", encoding="utf-8")

        with patch.object(pipeline, "_run", side_effect=self._fake_run):
            pipeline.run_showdown_pipeline(self.job_dir, "pokemon", "doubles", "p1", self._on_progress)

        script, args = self.calls[0]
        self.assertIn("--files", args)

    def test_raises_step_failed_when_no_replay_source_present(self):
        with patch.object(pipeline, "_run", side_effect=self._fake_run):
            with self.assertRaises(pipeline.StepFailed):
                pipeline.run_showdown_pipeline(self.job_dir, "pokemon", "doubles", "p1", self._on_progress)

    def test_empty_urls_file_raises_step_failed_not_a_crash(self):
        (self.job_dir / "replay_urls.txt").write_text("   \n\n", encoding="utf-8")
        with patch.object(pipeline, "_run", side_effect=self._fake_run):
            with self.assertRaises(pipeline.StepFailed):
                pipeline.run_showdown_pipeline(self.job_dir, "pokemon", "doubles", "p1", self._on_progress)

    def test_runs_compose_schema_and_the_three_analytics_scripts_after_import(self):
        (self.job_dir / "replay0.html").write_text("dummy", encoding="utf-8")

        with patch.object(pipeline, "_run", side_effect=self._fake_run):
            pipeline.run_showdown_pipeline(self.job_dir, "pokemon", "doubles", "p1", self._on_progress)

        scripts_called = [c[0] for c in self.calls]
        self.assertEqual(scripts_called,
                         ["showdown_import.py", "compose_schema.py",
                          "battle_record.py", "player_report.py", "coach_report.py"])
        # never touches video/AI-specific scripts
        self.assertNotIn("structure_pass.py", scripts_called)
        self.assertNotIn("analyze_matches.py", scripts_called)
        self.assertNotIn("transcribe.py", scripts_called)

    def test_progress_callback_fires_for_every_showdown_step(self):
        (self.job_dir / "replay0.html").write_text("dummy", encoding="utf-8")
        with patch.object(pipeline, "_run", side_effect=self._fake_run):
            pipeline.run_showdown_pipeline(self.job_dir, "pokemon", "doubles", "p1", self._on_progress)
        self.assertEqual([step for step, _ in self.progress], pipeline.STEPS_SHOWDOWN)


class TestCreateJobWithShowdownSourceType(unittest.TestCase):
    """Round-trips a source_type="showdown" job through the same local-mode
    job store test_local_dev_mode.py exercises, confirming the new `player`
    field actually persists (this is what a Supabase-configured deployment
    also needs supabase_schema.sql's new `player` column for)."""

    @classmethod
    def setUpClass(cls):
        from backend import auth as auth_module
        from backend import jobs as jobs_module
        if auth_module.configured():
            raise unittest.SkipTest("Supabase IS configured in this environment - "
                                     "local-mode tests don't apply here.")
        cls.auth_module = auth_module
        cls.jobs_module = jobs_module
        cls._tmp = tempfile.mkdtemp()
        cls._orig_jobs_dir = jobs_module.JOBS_DIR
        jobs_module.JOBS_DIR = type(cls._orig_jobs_dir)(cls._tmp)
        jobs_module._LOCAL_JOBS.clear()
        jobs_module._local_discovered = False

    @classmethod
    def tearDownClass(cls):
        cls.jobs_module.JOBS_DIR = cls._orig_jobs_dir
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_player_field_round_trips_and_total_steps_matches_showdown(self):
        user_id = self.auth_module.LOCAL_USER["id"]
        job = self.jobs_module.create_job(user_id=user_id, game="pokemon", mode="doubles",
                                           source_type="showdown", player="Geordivgc")
        self.assertEqual(job["source_type"], "showdown")
        self.assertEqual(job["player"], "Geordivgc")
        self.assertEqual(job["total_steps"], len(pipeline.STEPS_SHOWDOWN))

        fetched = self.jobs_module.get_job(job["job_id"], user_id)
        self.assertEqual(fetched["player"], "Geordivgc")

    def test_player_defaults_to_none_for_video_jobs(self):
        user_id = self.auth_module.LOCAL_USER["id"]
        job = self.jobs_module.create_job(user_id=user_id, game="pokemon", mode="doubles",
                                           source_type="url", url="https://example.com/vod")
        self.assertIsNone(job.get("player"))


if __name__ == "__main__":
    unittest.main()
