# Accuracy eval harness

Two tiers, because "is this accurate" splits into two very different questions:

## 1. Deterministic logic (this folder, `tests/*.py`)

Plain-library `unittest` - no pytest, no network, nothing to install. Covers
everything that's pure code and has no business calling Gemini or reading a
video: the species-legality allowlist, Mega/regional-form normalization,
Species Clause deduplication, `backend/analytics.py`'s aggregations (run
against the real seeded demo data), `skill_scores.py`'s scoring behavior,
`grade_matches.py`'s own CSV-merge logic, `showdown_import.py`'s replay
parsing (run against a real, public replay's actual battle log - unlike the
video pipeline, this one's 100% deterministic, so it's tested with exact
expected values throughout, not just invariants), frame de-duplication and
the Gemini Batch API's pure logic, the Showdown `source_type` job pipeline
dispatch (`test_showdown_job_pipeline.py`), reference-frame tagging
(`test_reference_frames.py`), the internal audit log
(`test_audit.py`), the frame-serving path-traversal guard plus
events.json/csv rewrite logic behind the event-correction endpoint
(`test_job_files.py`), that every subprocess `backend/pipeline.py` shells
out to gets a forced-UTF-8 environment so an emoji print can't silently crash
it on Windows (`test_pipeline_subprocess.py`), and the roster-constraint
wording in `build_event_prompt()` that keeps a genuine fuzzy misread
separate from a Pokemon that isn't in the known roster at all, plus the
team-preview "brought" (pick-4) closed-set narrowing on top of it - see
`ARCHITECTURE_HANDOFF.md` section 2f (`test_build_event_prompt.py`, 11
tests total). Also covers the OCR accuracy tier (`--use-ocr-tier`, ON BY
DEFAULT as of 2026-07-04 - see `ARCHITECTURE_HANDOFF.md` section 2d): the
deterministic on-screen-text-to-event parser (`test_battle_text_parser.py`,
34 tests), the OCR region-extraction/preprocessing wiring
(`test_ocr_battle_reader.py`, 14 tests, synthetic frames), the nickname/
species resolution layer (`test_pokemon_identity.py`, 14 tests), and the
merge logic that combines OCR-derived events with the existing Gemini
reads (`test_ocr_pipeline.py`, 20 tests, fake vision calls - never a live
API call).

Run everything:

```
py -m unittest discover -s tests -v
```

Run one file:

```
py -m unittest tests.test_species_legality -v
```

**Run this after ANY change to:** `analyze_matches.py`'s `ALLOWED_SPECIES` or
normalization functions, `backend/analytics.py`, `skill_scores.py`, or
`grade_matches.py`. It takes under a second and would have caught, as actual
failing tests instead of a user report, several of the real bugs fixed during
this project (Dragalge/Qwilfish wrongly rejected, Alolan Ninetales wrongly
rejected, Mawile + Mawile (Mega) double-counted, a `None`-vs-`str` crash in
`sorted()`).

Every test here is written against a REAL case that actually happened, not a
hypothetical - see each test's docstring for which bug it guards against.
**When you fix the next real bug, add a test for it here before moving on** -
that's what keeps this list growing instead of the same bug class recurring
in a new game later.

## 2. Vision/video accuracy (needs a human - `grade_matches.py`)

Nothing above can tell you whether Gemini correctly read a roster or a
winner off real footage - that requires a human to actually look at the
frames and confirm. `grade_matches.py` doesn't grade anything itself; it
removes the busywork around doing that grading pass:

```
py grade_matches.py --video test.mp4 --matches 3,14,20,21
```

For each match number, it extracts the exact roster-preview and result-screen
frames the system used (same windows/resolution as `analyze_matches.py`'s
first attempt) into `grading/match_<N>/`, and writes a row per match into
`grade_accuracy.csv` with the system's current read already filled in and
blank `actual_roster` / `actual_winner` / `correct?` / `notes` columns.

Then: open the JPGs, compare against what the system said, fill in the blank
columns by hand. Re-running the tool for a match you've already graded
replaces its row (your hand-filled grade for OTHER matches is untouched) so
you can re-check something after a fix without losing prior grading work.

This is genuinely the part that needs a person - there's no way to
independently verify "what actually happened in this video" without watching
it, so treat a growing, honestly-filled-in `grade_accuracy.csv` as the real
ground-truth asset this project is building, not a checkbox to skip.

## What this does NOT cover yet

- No CI / automatic-run-on-every-change wiring - these are run by hand today.
  Worth adding once this deploys anywhere with a build step.
- No per-game eval sets yet, because there's only one game (Pokemon Champions
  doubles) - when a second game gets onboarded (see `ADDING_A_NEW_GAME.md`),
  it needs its own `test_<game>_legality.py`-style file and its own
  `grade_matches.py` pass on a few of its own clips before you trust it.
