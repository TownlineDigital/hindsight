"""
Tests for gemini_batch.py.

Part 1 (TestPureLogic, TestParseResultLine) exercises real code with no
mocking at all - encode/decode_key, request-line building, result-line
parsing are pure functions with zero network dependency.

Part 2 (TestOrchestrationWithFakeClient) uses a fake stub client (plain
Python objects, no google-genai needed) to verify submit_battle_batch/
wait_for_batch/collect_battle_batch_results call the SDK in the right
sequence with the right arguments. This does NOT prove Google's real batch
endpoint accepts these calls - only that the code constructs and sequences
them the way the documented pattern requires. See gemini_batch.py's module
docstring for the honest caveat: the real network path is untested here.

Run: py -m unittest tests.test_gemini_batch -v   (from poc-starter/)
"""

import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import gemini_batch as gb  # noqa: E402


class TestKeyEncoding(unittest.TestCase):
    def test_round_trip(self):
        key = gb.encode_key(3, 7)
        self.assertEqual(key, "match3::chunk7")
        self.assertEqual(gb.decode_key(key), (3, 7))

    def test_decode_rejects_malformed_key(self):
        for bad in ["not-a-key", "match3chunk7", "", None, "match::chunk7"]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    gb.decode_key(bad)


class TestBuildRequestLine(unittest.TestCase):
    def test_produces_valid_jsonl_with_key_and_file_refs(self):
        line = gb.build_request_line(
            "match1::chunk0", "read these frames",
            [("fake://uri1", "image/jpeg"), ("fake://uri2", "image/jpeg")],
        )
        parsed = json.loads(line)
        self.assertEqual(parsed["key"], "match1::chunk0")
        parts = parsed["request"]["contents"][0]["parts"]
        self.assertEqual(parts[0]["text"], "read these frames")
        self.assertEqual(len(parts) - 1, 2)   # one part per file_ref, plus the text part
        self.assertEqual(parts[1]["file_data"]["file_uri"], "fake://uri1")

    def test_no_images_still_produces_valid_request(self):
        line = gb.build_request_line("match2::chunk0", "text only", [])
        parsed = json.loads(line)
        self.assertEqual(len(parsed["request"]["contents"][0]["parts"]), 1)


class TestParseResultLine(unittest.TestCase):
    def test_successful_result(self):
        line = json.dumps({
            "key": "match1::chunk0",
            "response": {"candidates": [{"content": {"parts": [{"text": '[{"event": "move_used"}]'}]}}]},
        })
        key, parsed, error = gb.parse_result_line(line)
        self.assertEqual(key, "match1::chunk0")
        self.assertEqual(parsed, [{"event": "move_used"}])
        self.assertIsNone(error)

    def test_result_wrapped_in_markdown_fence(self):
        """Gemini sometimes wraps JSON output in ```json ... ``` even when
        asked not to - the same tolerance analyze_matches._json_from_text
        already has for live calls must hold for batch results too."""
        text = '```json\n[{"event": "move_used"}]\n```'
        line = json.dumps({"key": "match1::chunk0",
                            "response": {"candidates": [{"content": {"parts": [{"text": text}]}}]}})
        key, parsed, error = gb.parse_result_line(line)
        self.assertEqual(parsed, [{"event": "move_used"}])
        self.assertIsNone(error)

    def test_error_result(self):
        line = json.dumps({"key": "match2::chunk1", "error": {"code": 500, "message": "internal error"}})
        key, parsed, error = gb.parse_result_line(line)
        self.assertEqual(key, "match2::chunk1")
        self.assertIsNone(parsed)
        self.assertIn("500", error)

    def test_empty_response_is_an_error_not_a_crash(self):
        line = json.dumps({"key": "match3::chunk0", "response": None})
        key, parsed, error = gb.parse_result_line(line)
        self.assertIsNone(parsed)
        self.assertIsNotNone(error)

    def test_unparseable_text_is_an_error_not_a_crash(self):
        line = json.dumps({"key": "match4::chunk0",
                            "response": {"candidates": [{"content": {"parts": [{"text": "not json at all"}]}}]}})
        key, parsed, error = gb.parse_result_line(line)
        self.assertIsNone(parsed)
        self.assertIn("could not parse", error)


class _FakeFilesAPI:
    def __init__(self):
        self.uploaded_paths = []
        self.uploaded_configs = []
        self._download_content = b""

    def upload(self, file, config=None):
        self.uploaded_paths.append(file)
        self.uploaded_configs.append(config)
        n = len(self.uploaded_paths)
        return SimpleNamespace(uri=f"fake-uri-{n}", name=f"files/fake{n}")

    def download(self, file):
        return self._download_content


class _FakeBatchesAPI:
    def __init__(self):
        self.create_calls = []
        self._get_states = []
        self._get_call_count = 0

    def create(self, model, src, config=None):
        self.create_calls.append({"model": model, "src": src, "config": config})
        return SimpleNamespace(name="batches/fake-job-1")

    def get(self, name):
        state_name = self._get_states[min(self._get_call_count, len(self._get_states) - 1)]
        self._get_call_count += 1
        job = SimpleNamespace(name=name, state=SimpleNamespace(name=state_name))
        if state_name == "JOB_STATE_SUCCEEDED":
            job.dest = SimpleNamespace(file_name="files/fake-results")
        return job


class _FakeClient:
    def __init__(self):
        self.files = _FakeFilesAPI()
        self.batches = _FakeBatchesAPI()


class TestOrchestrationWithFakeClient(unittest.TestCase):
    """Verifies the CALL SEQUENCE and arguments, not that Google's real
    endpoint accepts them - see module docstring for the honest caveat."""

    def test_submit_uploads_each_unique_image_once_and_the_jsonl_once(self):
        client = _FakeClient()
        chunks_by_key = {
            (1, 0): [("frameA.jpg", 0.0), ("frameB.jpg", 1.0)],
            (1, 1): [("frameC.jpg", 2.0)],
        }
        # ONE prompt PER CHUNK (not per match) - each embeds that chunk's own
        # timestamps, see build_event_prompt() / submit_battle_batch()'s docstring.
        prompts_by_key = {(1, 0): "read frames at 0s, 1s", (1, 1): "read frame at 2s"}

        job_name = gb.submit_battle_batch(client, "gemini-2.5-flash", chunks_by_key, prompts_by_key)

        self.assertEqual(job_name, "batches/fake-job-1")
        # 3 unique frame images + 1 JSONL file = 4 upload() calls
        self.assertEqual(len(client.files.uploaded_paths), 4)
        self.assertEqual(len(client.batches.create_calls), 1)
        self.assertEqual(client.batches.create_calls[0]["model"], "gemini-2.5-flash")

    def test_submit_reuses_upload_for_a_path_seen_in_multiple_chunks(self):
        """If the same frame path somehow appears in two chunks, it should
        only be uploaded once - re-uploading identical bytes wastes nothing
        functionally but is worth guarding since it would double real cost."""
        client = _FakeClient()
        chunks_by_key = {
            (1, 0): [("shared.jpg", 0.0)],
            (1, 1): [("shared.jpg", 0.0)],
        }
        gb.submit_battle_batch(client, "gemini-2.5-flash", chunks_by_key, {(1, 0): "prompt", (1, 1): "prompt"})
        image_uploads = [p for p in client.files.uploaded_paths if p == "shared.jpg"]
        self.assertEqual(len(image_uploads), 1)

    def test_wait_for_batch_polls_until_terminal_state(self):
        client = _FakeClient()
        client.batches._get_states = ["JOB_STATE_PENDING", "JOB_STATE_RUNNING", "JOB_STATE_SUCCEEDED"]
        polled_states = []

        with patch.object(gb.time, "sleep"):   # don't actually wait in a test
            job = gb.wait_for_batch(client, "batches/fake-job-1", poll_interval=1,
                                     on_poll=polled_states.append)

        self.assertEqual(job.state.name, "JOB_STATE_SUCCEEDED")
        self.assertEqual(polled_states, ["JOB_STATE_PENDING", "JOB_STATE_RUNNING"])

    def test_collect_results_correlates_by_key_and_skips_unrecognized_keys(self):
        client = _FakeClient()
        lines = [
            json.dumps({"key": "match1::chunk0",
                        "response": {"candidates": [{"content": {"parts": [{"text": "[]"}]}}]}}),
            json.dumps({"key": "match1::chunk1", "error": {"message": "boom"}}),
            json.dumps({"key": "not-a-real-key", "response": {}}),   # must be skipped, not crash
        ]
        client.files._download_content = ("\n".join(lines)).encode("utf-8")
        fake_job = SimpleNamespace(state=SimpleNamespace(name="JOB_STATE_SUCCEEDED"),
                                    dest=SimpleNamespace(file_name="files/fake-results"))

        results = gb.collect_battle_batch_results(client, fake_job)

        self.assertEqual(set(results.keys()), {(1, 0), (1, 1)})
        self.assertEqual(results[(1, 0)], ([], None))
        self.assertEqual(results[(1, 1)][0], None)
        self.assertIn("boom", results[(1, 1)][1])


if __name__ == "__main__":
    unittest.main()
