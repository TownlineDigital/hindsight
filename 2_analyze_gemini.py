"""
STEP 2 - Send the frames to Gemini and get back structured events.

What it does:
  1. Reads your event schema from schema.json (edit that file for your game).
  2. Loads the frames from the frames/ folder, using frames/manifest.csv to
     know the exact timestamp of each one (works for both uniform and scene mode).
  3. Sends them to Gemini in small batches, asking for JSON only.
  4. Saves the result to events.json AND events.csv.

You need a Gemini API key (free to start). The README explains how to get one.
This script reads it from an environment variable called GEMINI_API_KEY.

Run it (after step 1):
  python 2_analyze_gemini.py
  python 2_analyze_gemini.py --batch 12
"""

import argparse
import concurrent.futures
import csv
import json
import os
import re
import sys
import time

try:
    from google import genai
    from google.genai import types
except ImportError:
    sys.exit("The Gemini library isn't installed yet. Run:  pip install google-genai")

# If a model name ever stops working, swap it for the current Flash model (see README).
MODEL = "gemini-2.5-flash"


def load_schema(path="schema.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_frames(frames_dir):
    """Return [(full_path, timestamp_seconds), ...] using manifest.csv when present."""
    manifest = os.path.join(frames_dir, "manifest.csv")
    if os.path.exists(manifest):
        rows = []
        with open(manifest, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append((os.path.join(frames_dir, r["filename"]), float(r["timestamp_seconds"])))
        return rows
    # Fallback: no manifest -> assume 1 frame per second in filename order.
    files = sorted(f for f in os.listdir(frames_dir) if f.lower().endswith((".jpg", ".jpeg", ".png")))
    return [(os.path.join(frames_dir, f), float(i)) for i, f in enumerate(files)]


def call_with_retry(client, parts, model, max_tries=3):
    """Call Gemini; if we hit a per-minute rate limit (429), wait and retry."""
    for attempt in range(max_tries):
        try:
            return client.models.generate_content(
                model=model,
                contents=parts,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
        except Exception as e:
            transient = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
            if transient and attempt < max_tries - 1:
                print(f"    rate limited — waiting 20s then retrying ({attempt+1}/{max_tries-1})...")
                time.sleep(20)
                continue
            raise


def parse_events(text):
    """Accept whatever shape Gemini returns and pull out the list of events.

    Handles: a bare JSON array, an object like {"events":[...]}, a single event
    object, a markdown-fenced block, or a JSON array buried in some prose.
    """
    if not text:
        return []
    t = text.strip()
    if t.startswith("```"):                       # strip ```json ... ``` fences
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    try:
        data = json.loads(t)
    except Exception:
        m = re.search(r"\[.*\]", t, re.DOTALL)    # last resort: grab an array
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except Exception:
            return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "event" in data or "timestamp" in data:
            return [data]
        for k in ("events", "results", "data", "items"):
            if isinstance(data.get(k), list):
                return data[k]
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


def build_prompt(schema, timestamps):
    lines = "\n".join(f"  Image {i+1} -> timestamp {ts}s" for i, ts in enumerate(timestamps))
    prompt = (
        f"You are an expert analyst of the game: {schema.get('game')}.\n"
        f"The {len(timestamps)} images below are consecutive moments from a clip, in time order:\n"
        f"{lines}\n\n"
        "Look carefully at EVERY image and report each game event you can see evidence for. "
        "Reading any on-screen text is your most reliable signal — transcribe what it says.\n"
        f"Use only these event types: {schema['event_types']}\n"
        "For each event return an object with exactly these fields: "
        f"{list(schema['fields_to_capture'].keys())}\n"
        "Use the timestamp of the image where you saw it.\n\n"
        "This is a DOUBLES format: TWO Pokemon per side are active (four on the field at once). "
        "Be thorough and lean toward OVER-reporting — collecting extra data is better than missing it. "
        "Include uncertain events with a low confidence value (around 0.3) rather than leaving them out. "
        "For EACH image that shows a battle, output one 'field_state' listing both of the player's active "
        "Pokemon (player_active) and both of the opponent's (opponent_active), with their HP in detail.\n"
        "RULES: (1) Report each discrete event once, at the timestamp it first appears. "
        "(2) Distinguish text: 'X used [Move]!' = move_used; 'A critical hit!' = critical_hit; "
        "'super effective' = super_effective_hit. "
        "(3) Before each match a TEAM PREVIEW screen shows both players' 6 Pokemon (each picks 4); emit one "
        "'team_preview' event listing the teams — it marks a new match starting. "
        "(4) A 'battle' is the WHOLE MATCH; in doubles it ends only when ALL of one side's brought (4) Pokemon "
        "have fainted (a 'You won!'/defeat/results screen). A single Pokemon fainting is 'pokemon_fainted', "
        "NEVER 'battle_end'. Emit 'battle_end' once per match with winner 'player' or 'opponent'.\n\n"
        f"Guidance: {schema.get('notes_for_the_ai','')}\n\n"
    )
    if schema.get("example_output"):
        prompt += ("Example of the output format expected (yours will describe THESE images):\n"
                   f"{json.dumps(schema['example_output'])}\n\n")
    prompt += ("Return ONLY a JSON array of event objects (start with [ and end with ]). "
               "No markdown, no commentary. Return [] only if no gameplay at all is visible in any image.")
    return prompt


def save_outputs(all_events, json_path="events.json", csv_path="events.csv"):
    """Write events.json + events.csv. Called after every batch so a crash or
    Ctrl+C never loses progress on a long run."""
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_events, f, indent=2)
    if all_events:
        keys = []
        for ev in all_events:
            for k in ev.keys():
                if k not in keys:
                    keys.append(k)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for ev in all_events:
                writer.writerow(ev)


def _ts_key(ev):
    try:
        return float(ev.get("timestamp"))
    except (TypeError, ValueError):
        return 0.0


def _run_batch(client, schema, model, chunk):
    """Worker: build one request, call Gemini, return the parsed events + raw text."""
    timestamps = [ts for _, ts in chunk]
    parts = [build_prompt(schema, timestamps)]
    for path, _ in chunk:
        with open(path, "rb") as img:
            parts.append(types.Part.from_bytes(data=img.read(), mime_type="image/jpeg"))
    resp = call_with_retry(client, parts, model)
    return parse_events(resp.text), resp.text


def analyze(frames_dir="frames", schema_path="schema.json", batch=12, model=MODEL, concurrency=6):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("No API key found. Set GEMINI_API_KEY first (see the README).")
    if not os.path.isdir(frames_dir):
        sys.exit(f"No '{frames_dir}' folder. Run step 1 first.")

    schema = load_schema(schema_path)
    frames = load_frames(frames_dir)
    if not frames:
        sys.exit(f"No images found in '{frames_dir}'. Run step 1 first.")

    client = genai.Client(api_key=api_key)
    jobs = [frames[b:b + batch] for b in range(0, len(frames), batch)]
    total = len(jobs)
    print(f"Analyzing {len(frames)} frames with {model}, {batch} per request "
          f"({total} requests, {concurrency} in parallel)...")

    all_events = []
    done = 0
    debug_shown = False
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=concurrency)
    futures = {ex.submit(_run_batch, client, schema, model, chunk): i for i, chunk in enumerate(jobs)}
    try:
        for fut in concurrent.futures.as_completed(futures):
            i = futures[fut]
            done += 1
            try:
                events, raw = fut.result()
                if not debug_shown:
                    debug_shown = True
                    print(f"  [debug] sample raw reply: {(raw or '').strip()[:200]}")
                all_events.extend(events)
                print(f"  [{done}/{total}] batch {i+1}: +{len(events)} | running total {len(all_events)}")
            except Exception as e:
                print(f"  [{done}/{total}] batch {i+1}: error -> {str(e)[:140]}")
            save_outputs(sorted(all_events, key=_ts_key))   # crash-safe save after each
    except KeyboardInterrupt:
        ex.shutdown(wait=False, cancel_futures=True)
        save_outputs(sorted(all_events, key=_ts_key))
        print(f"\nStopped early. Saved {len(all_events)} events so far to events.json / events.csv.")
        return
    ex.shutdown(wait=True)

    save_outputs(sorted(all_events, key=_ts_key))
    print(f"\nDone. {len(all_events)} total events -> events.json and events.csv")
    print("Next: run  py 4_battle_record.py  for the win/loss record.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze frames with Gemini.")
    parser.add_argument("--frames", default="frames", help="Folder with the extracted frames")
    parser.add_argument("--schema", default="schema.json", help="Your event schema file")
    parser.add_argument("--batch", type=int, default=12, help="Frames per request (default: 12)")
    parser.add_argument("--model", default=MODEL,
                        help=f"Gemini model (default: {MODEL}; cheaper option). Try gemini-3.5-flash for accuracy.")
    parser.add_argument("--concurrency", type=int, default=6,
                        help="How many requests to run in parallel (default: 6). Higher = faster, but watch rate limits.")
    args = parser.parse_args()
    analyze(args.frames, args.schema, args.batch, args.model, args.concurrency)
