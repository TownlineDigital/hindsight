"""
GEMINI BATCH API HELPERS - lets analyze_matches.py run the bulk per-match
battle-frame event extraction (the single biggest line item in this
project's Gemini bill - see ARCHITECTURE_HANDOFF.md section 2a) through
Google's Batch API instead of live synchronous calls: exactly 50% off both
input and output tokens, the SAME model and quality, in exchange for not
being instant (Google's target turnaround is 24 hours, "in majority of cases
much quicker" - see https://ai.google.dev/gemini-api/docs/batch-api). Video
analysis doesn't need real-time results, so this is a real cost win with no
accuracy tradeoff.

This file is split deliberately into two halves:

  1. PURE LOGIC (encode_key, decode_key, build_request_line, parse_result_line)
     - no network calls, fully unit-tested (tests/test_gemini_batch.py) with
     zero dependency on google-genai actually being installed or a live API
     key. This is the part you can trust is correct without ever running a
     real batch job.

  2. ORCHESTRATION (submit_battle_batch, wait_for_batch, collect_batch_results)
     - the actual client.files.upload / client.batches.create / .get /
     .download calls. These follow Google's documented pattern exactly (see
     each function's docstring for the specific doc line it's based on), but
     could NOT be exercised against Google's real batch endpoint while
     building this (no live API key/network available in the environment
     this was built in) - tested here only with a fake stub client that
     verifies the CALL SEQUENCE and arguments are correct, not that Google's
     servers actually accept them. Treat your first real --use-batch-api run
     as the real end-to-end test, the same way the Supabase/accounts work
     earlier in this project was flagged as untested-until-you-run-it.

Batch job requests use the file-based JSONL path (not inline requests) with
a custom "key" per request, per Google's own recommendation for anything
past a trivial size or with multimodal (image) content:
  "For a large number of requests, always use the file input method... If
  you are working with multimodal input, you can reference other uploaded
  files within your JSONL file." - ai.google.dev/gemini-api/docs/batch-api
"""

import json
import re
import time

# --------------------------------------------------------------------------
# 1. PURE LOGIC - no network, fully unit-testable
# --------------------------------------------------------------------------

_KEY_RE = re.compile(r"^match(\d+)::chunk(\d+)$")


def encode_key(match_idx, chunk_idx):
    """A batch request needs a caller-defined "key" so results can be
    matched back to which match/chunk they came from once they arrive,
    possibly hours later and in arbitrary order - see PROTOCOL note above."""
    return f"match{match_idx}::chunk{chunk_idx}"


def decode_key(key):
    """Inverse of encode_key(). Raises ValueError on anything that doesn't
    match the expected shape, rather than silently returning nonsense -
    a malformed key means a result can't be safely attributed to a match."""
    m = _KEY_RE.match(key or "")
    if not m:
        raise ValueError(f"Not a valid batch key: {key!r}")
    return int(m.group(1)), int(m.group(2))


def build_request_line(key, prompt, file_refs, temperature=0.1):
    """One line of the JSONL file the Batch API's file-input mode expects.
    file_refs: [(file_uri, mime_type), ...] for images ALREADY uploaded via
    the Files API (client.files.upload) - a batch request references
    uploaded files by URI, it doesn't carry raw image bytes inline."""
    parts = [{"text": prompt}]
    for uri, mime_type in file_refs:
        parts.append({"file_data": {"mime_type": mime_type, "file_uri": uri}})
    request = {
        "contents": [{"role": "user", "parts": parts}],
        "generation_config": {"response_mime_type": "application/json", "temperature": temperature},
    }
    return json.dumps({"key": key, "request": request})


def parse_result_line(line):
    """One line of the JSONL the Batch API returns once a job succeeds.
    Returns (key, parsed_json_or_None, error_message_or_None) - exactly one
    of the last two will be set. Never raises on a malformed/error line;
    the caller (collect_battle_batch_results) is what decides what a
    missing/errored result means for that match's data."""
    data = json.loads(line)
    key = data.get("key")

    error = data.get("error")
    if error:
        return key, None, str(error)

    response = data.get("response")
    if not response:
        return key, None, "empty response (no 'response' field in result line)"

    try:
        text = response["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return key, None, "response had no text content"

    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return key, json.loads(text), None
    except (json.JSONDecodeError, ValueError):
        m = re.search(r"[\[{].*[\]}]", text, re.DOTALL)
        if m:
            try:
                return key, json.loads(m.group(0)), None
            except (json.JSONDecodeError, ValueError):
                pass
        return key, None, f"could not parse response text as JSON: {text[:100]!r}"


# Terminal states a batch job can end in - see
# ai.google.dev/gemini-api/docs/batch-api's job-lifecycle section.
TERMINAL_STATES = {"JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}


# --------------------------------------------------------------------------
# 2. ORCHESTRATION - the real client.* calls (untested against a live API
#    key/network - see module docstring)
# --------------------------------------------------------------------------

def submit_battle_batch(client, model, chunks_by_key, prompts_by_key, display_name="analyze-matches-batch"):
    """chunks_by_key: {(match_idx, chunk_idx): [(image_path, timestamp), ...]}
    prompts_by_key: {(match_idx, chunk_idx): prompt_text} - ONE prompt PER
    CHUNK, not per match, since analyze_matches.build_event_prompt() embeds
    that chunk's own image-to-timestamp mapping ("Image 1 -> 45s") into the
    prompt text itself - two chunks from the same match need two different
    prompts even though they share the same roster. Build each with
    build_event_prompt(schema, roster, chunk_timestamps) before calling this.

    Uploads every image once via the Files API, builds one JSONL line per
    chunk (each referencing its own images by the uploaded file's URI - see
    build_request_line), uploads that JSONL, and submits ONE batch job
    covering every match/chunk given. Returns the job's resource name (used
    to poll/collect later - safe to save this to disk and resume in a
    separate process/run, since a batch job can take a while)."""
    import tempfile
    from pathlib import Path

    file_refs_cache = {}   # image_path -> (uri, mime_type), so a path reused across chunks uploads once

    def uploaded_ref(path):
        if path not in file_refs_cache:
            f = client.files.upload(file=path)
            file_refs_cache[path] = (f.uri, "image/jpeg")
        return file_refs_cache[path]

    lines = []
    for (match_idx, chunk_idx), frame_chunk in chunks_by_key.items():
        key = encode_key(match_idx, chunk_idx)
        prompt = prompts_by_key[(match_idx, chunk_idx)]
        file_refs = [uploaded_ref(path) for path, _ in frame_chunk]
        lines.append(build_request_line(key, prompt, file_refs))

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        f.write("\n".join(lines))
        jsonl_path = f.name

    try:
        uploaded_jsonl = client.files.upload(
            file=jsonl_path,
            config={"display_name": f"{display_name}-requests", "mime_type": "jsonl"},
        )
        batch_job = client.batches.create(
            model=model, src=uploaded_jsonl.name, config={"display_name": display_name},
        )
    finally:
        Path(jsonl_path).unlink(missing_ok=True)

    return batch_job.name


def wait_for_batch(client, job_name, poll_interval=30, on_poll=None):
    """Blocks, polling client.batches.get(), until the job reaches a
    terminal state (see TERMINAL_STATES). on_poll(state_name), if given, is
    called after every poll - analyze_matches.py uses this to print
    progress so a long wait isn't a silent hang."""
    job = client.batches.get(name=job_name)
    while job.state.name not in TERMINAL_STATES:
        if on_poll:
            on_poll(job.state.name)
        time.sleep(poll_interval)
        job = client.batches.get(name=job_name)
    return job


def collect_battle_batch_results(client, job):
    """job: a finished batch job (job.state.name == "JOB_STATE_SUCCEEDED").
    Downloads the result JSONL and returns {(match_idx, chunk_idx):
    (parsed_json_or_None, error_or_None)}, keyed by the same tuple
    chunks_by_key used in submit_battle_batch - decode_key() is what
    connects the two."""
    result_file_name = job.dest.file_name
    content = client.files.download(file=result_file_name).decode("utf-8")

    results = {}
    for line in content.splitlines():
        if not line.strip():
            continue
        key, parsed, error = parse_result_line(line)
        try:
            match_idx, chunk_idx = decode_key(key)
        except ValueError:
            continue   # a result with an unrecognized key can't be attributed - skip rather than guess
        results[(match_idx, chunk_idx)] = (parsed, error)
    return results
