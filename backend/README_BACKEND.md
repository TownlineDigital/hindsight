# Backend API

Implements the contract in `ARCHITECTURE_HANDOFF.md` section 8. Wraps the existing
pipeline scripts as background jobs and serves their outputs as JSON — no
pipeline script was rewritten, only three were renamed (see below) so their
functions could be imported.

## Run it

**Quickest path - no cloud setup at all (local dev mode):** if you just want
to check the dashboard/pipeline output, skip straight to:

```
py -m pip install -r requirements.txt
py -m uvicorn backend.main:app --reload --port 8000
```

Leave `.env` and `frontend/.env` unfilled (or don't create them yet). The app
detects that Supabase isn't configured and runs as a single local user with
no sign-in screen - same behavior as before accounts existed. Open
`http://127.0.0.1:8000/dashboard/` and you should see the seeded `demo` job
straight away, since `jobs/demo/` was already seeded earlier in this project.
See "Local dev mode" below for exactly how this works.

**Full setup with real accounts** (multi-user, persists per-account - see
"Accounts" below for the full walkthrough):

1. Create a free Supabase project, run `supabase_schema.sql` in its SQL Editor.
2. `copy .env.example .env` (in `poc-starter/`) and fill in `GEMINI_API_KEY`,
   `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.
3. `copy frontend\.env.example frontend\.env` and fill in `VITE_SUPABASE_URL`,
   `VITE_SUPABASE_ANON_KEY` (the *anon* key, not service_role).
4. Rebuild the frontend so it picks up the new env vars (`cd frontend && npm
   run build && cd ..`).
5. Sign up once at the frontend's login screen, then find your new user's UUID
   in the Supabase dashboard (Authentication -> Users) and run
   `py seed_demo_job.py --user-id <that-uuid>` so the demo data shows up in
   your account.

**Every time after that**, from `poc-starter/`:

```
py -m uvicorn backend.main:app --reload --port 8000
```

Then open:
- `http://127.0.0.1:8000/dashboard/` — the React dashboard (see "Frontend"
  below). Sign-in screen only appears once Supabase is actually configured
  (see "Local dev mode" / "Accounts").
- `http://127.0.0.1:8000/docs` — interactive API docs (FastAPI generates this
  from the code). In local dev mode every route works without a token; once
  Supabase is configured, `/jobs...` routes need a real Bearer token, so
  `/docs`'s "Try it out" won't work against them without one - it's still
  useful for `/meta/{format}`, which isn't user-scoped either way.

## Local dev mode (no Supabase required)

`backend/auth.py`'s `current_user()` and every function in `backend/jobs.py`
check `auth.configured()` (true only when `SUPABASE_URL` AND
`SUPABASE_SERVICE_ROLE_KEY` are both set). When it's false:

- Every request is treated as one fixed user (`auth.LOCAL_USER`) - no sign-in
  required, no token checked.
- Jobs live in an in-memory dict instead of Postgres, and `jobs/<id>/` folders
  that already have `events.json` (like the seeded `jobs/demo/`) are picked up
  automatically - the same folder-discovery behavior the pre-accounts version
  of `jobs.py` had.
- The frontend calls `GET /auth/status` on load and skips the sign-in screen
  entirely when `accounts_required` comes back `false`.

This isn't a special test/debug flag to remember to turn off - it's just what
happens automatically when `.env` hasn't been filled in yet. Fill in real
Supabase credentials whenever you want real multi-user accounts, and the exact
same code requires real sign-in from that point on, no code changes needed.
Covered by `tests/test_local_dev_mode.py`.

## Endpoints

| | |
|---|---|
| `POST /jobs` | multipart form: `source_type` (`url`, `upload`, or `showdown`), `game`, `mode` (`doubles` default or `singles`), `regulation` (`m-b` default, current, or `m-a`, launch/superseded — see ARCHITECTURE_HANDOFF.md §3a), plus `url`/`file` (video) or `files`/`urls`/`player` (Showdown replay(s) — see below). Starts the pipeline in the background, returns `{job_id, status, ...}` immediately. |
| `GET /jobs` | list all jobs (not in the original contract, added for convenience while testing). |
| `GET /jobs/{id}` | status, current step, matches found so far, rough cost estimate. |
| `GET /jobs/{id}/matches` | `matches.csv` as JSON. |
| `GET /jobs/{id}/events` | `events.json`, unmodified. |
| `GET /jobs/{id}/record` | `{matches, wins, losses, win_rate, by_lead, by_bring}`. |
| `GET /jobs/{id}/report` | everything in `coach_report.md` / `player_report.md`, as JSON (combat stats, Tera win rates, toughest matchups, usage, coaching flags). |
| `POST /jobs/{id}/coach` | `{question}` → `{answer}`, wraps `coach_chat.answer()`. |
| `GET /meta/{format}` | serves `meta/<format>.json`; 404 with a hint if you haven't run `meta_build.py` yet. |
| `GET /jobs/{id}/matches/summary` | not in the original contract — result, lead, brought, KOs, duration per match (what the dashboard's Matches table actually shows). |
| `GET /jobs/{id}/opponent-strength` | not in the original contract — type-overlap risk score per opponent's brought 4, correlated against your actual win/loss (see `backend/type_synergy.py`). |
| `GET /jobs/{id}/skill-scores` | not in the original contract — the 4 progression scores (tempo/adaptability/execution/closing) + confidence tier from `skill_scores.py`. This was written early on but never wired into the API until the frontend rework; see "Frontend" below. |
| `GET /jobs/{id}/frame/{path}` | not in the original contract — serves one stored reference image (e.g. an event's `reference_frame` path), ownership-checked and path-traversal-guarded (`backend/job_files.safe_frame_path()`). See "Data retention & manual corrections" below. |
| `PATCH /jobs/{id}/events/{index}` | not in the original contract — `{fields: {...}}` corrects one or more fields on a single event by hand (e.g. a misread Pokémon), returns the updated event. See "Data retention & manual corrections" below. |

### Data retention & manual corrections

Nothing a job produces gets auto-deleted anymore — `structure_frames/`/`match_frames/`
used to be `shutil.rmtree()`'d once a job finished; that whole-job cleanup is gone (see
`backend/pipeline.py`). `analyze_matches.py` was also changed to sample each match's
frames into its own subfolder (`match_frames/match_<N>/...`) rather than one shared
folder reused (and wiped) across matches, since otherwise later matches' frames would
silently overwrite earlier ones on disk.

That said, each match's frame folder doesn't just grow forever — right after a match's
roster/battle/winner reads finish, `analyze_matches.prune_unreferenced_frames()` deletes
everything in that match's folder except the (usually small) subset of frames actually
kept as an event's `reference_frame`. This exists because the earlier "keep literally
everything" version caused a real problem: with hundreds of frames per match piling up
across every job, `uvicorn --reload`'s file watcher had to track so many files that it
could stop responding to requests at all (if your dashboard ever hangs on load, try
running uvicorn without `--reload`, or add `--reload-exclude "jobs/*"`). Pruning keeps
the reference-photo/correction feature fully working while keeping disk usage bounded.

Every extracted event now carries a `reference_frame` — the path to whichever sampled
frame was closest in time to that event (`analyze_matches.attach_reference_frames()`,
wired into both live and `--use-batch-api` modes). `GET /jobs/{id}/frame/{path}` serves
that image back, and `PATCH /jobs/{id}/events/{index}` lets a signed-in user correct a
wrong AI call by hand — both used by the dashboard's Matches tab (click a match to
expand its events, each with a thumbnail and a "Correct this" form). Corrections are
recorded (before/after) to `backend/audit.py`'s internal audit log, which also tracks
job lifecycle events (`job_created`/`job_step`/`job_completed`/`job_failed`) — this log
is NOT user-facing (no endpoint reads it); it's a local `audit_log.jsonl` file plus,
when Supabase is configured, a service-role-only `audit_log` table (see
`supabase_schema.sql`) for internal review.

Known limitation: correcting one event does not retroactively recompute a match's
already-derived summary fields (brought/lead/winner, on that match's
`team_preview`/`battle_end` events) — see `ARCHITECTURE_HANDOFF.md` section 2c.

### `source_type="showdown"` — submitting Pokémon Showdown replays instead of video

`POST /jobs` accepts a third source type alongside video's `url`/`upload`: `showdown`,
which runs `showdown_import.py` instead of the video/Gemini pipeline (no FFmpeg, no
AI call at all — see `ARCHITECTURE_HANDOFF.md` section 2a/2b). Pass exactly one of:

- `files` — one or more uploaded replay `.html`/`.json` files (combined into one job
  as consecutive matches, same as `showdown_import.py --files`).
- `urls` — one or more live replay URLs (`replay.pokemonshowdown.com/...`), as an
  alternative to uploading files (same as `showdown_import.py --urls`).

Plus `player` (default `"p1"`) — which side is "you" in the replay(s): a Showdown
username (case-insensitive) or `"p1"`/`"p2"`. A replay has no built-in notion of "the
player" the way a video of your own POV does, so this is the one thing that has to be
told explicitly, same as the CLI.

A Showdown job has a *shorter* step list than a video job (`get_replays →
compose_schema → battle_record → player_report → coach_report` — see
`backend/pipeline.py`'s `STEPS_SHOWDOWN`), since there's no video to fetch, no
`structure_pass` (no video to scan for match boundaries), no `analyze_matches` (no
Gemini call), and no `transcribe` (no audio track). `GET /jobs/{id}` reports the
right `total_steps` for whichever source type the job actually is. Every other
endpoint — record, report, matches/summary, skill-scores, opponent-strength, coach —
works completely unchanged, since a Showdown job's `events.json` has the identical
shape a video job's does.

Requires `player text` on the `jobs` table (see `supabase_schema.sql` — added via
`alter table ... add column if not exists`, safe to re-run even if you already have
the table).

## Design choices (so the "why" isn't a mystery later)

- **One folder per job (`jobs/<job_id>/`), scripts run as subprocesses with
  `cwd` set to that folder.** The scripts write to hardcoded relative names
  (`events.json`, `matches.csv`, ...) — rather than editing every script to
  accept an output path, each job just gets its own folder so nothing
  collides. This is the same pattern `run_full.py` already uses, just with a
  different `cwd` per job instead of one shared folder.
- **The three pure-analytics scripts were renamed** (`4_battle_record.py` →
  `battle_record.py`, `5_player_report.py` → `player_report.py`,
  `6_coach_report.py` → `coach_report.py`) so `backend/analytics.py` can
  `import` their functions (`per_match`, `winrate_table`, ...) instead of
  re-implementing win-rate math. `run_full.py` was updated to match. This is
  the refactor the handoff doc explicitly asked for.
- **Background jobs run on a plain Python thread per job**, but the job
  *metadata* (status, step, owner, cost estimate, ...) now lives in Postgres
  (see "Accounts" below and `backend/jobs.py`) instead of an in-memory dict -
  that's what changed to make jobs survive a server restart and be scoped
  per user. The thread-per-job execution model itself is still the simplest
  thing that works for one person's traffic; swap it for a real queue
  (Celery/RQ, as the handoff's stack section suggests) once more than one
  person needs to run jobs at the same time, since right now a restart mid-run
  does still lose that one in-flight job's progress (though not its row - it'll
  just be stuck showing "running" until you manually mark it failed or re-run it).
- **`GET /meta/{format}` reads a project-level file**, not a per-job one. The
  meta file is a running "own-data flywheel" across every match you've ever
  processed, so it isn't scoped to a single job.
- **The dashboard is now the React app in `frontend/`** (see "Frontend" below),
  built and dropped into `backend/static/`, still mounted at `/dashboard` via
  FastAPI's `StaticFiles` — same serving mechanism as before, just a real
  build now instead of one hand-written HTML file. It's still read-only (no
  upload form yet). The original plain HTML/JS version is kept at
  `backend/static_legacy/index.html` in case you ever want to compare or fall
  back to it (open that file directly in a browser, or point `StaticFiles` at
  it temporarily — it's not wired into `/dashboard` automatically).

## Data-quality fixes applied along the way

A few real bugs surfaced while building/testing this and got fixed rather than
worked around:

- **Jobs failing on Windows with a truncated traceback ending mid-line** —
  found while doing the first real end-to-end dashboard test on a Windows
  machine. `analyze_matches.py` prints a 🚫 emoji when it rejects an illegal
  species; that's harmless when the script is run directly in a terminal
  (Windows' console layer handles Unicode fine), but `backend/pipeline.py`'s
  `_run()` shells it out with `subprocess.run(..., capture_output=True,
  text=True)` - no explicit encoding. With stdout/stderr redirected to a pipe
  instead of a real console, Python falls back to the OS's legacy locale
  encoding (often cp1252 on Windows), which can't represent the emoji - so the
  CHILD process crashed with an unhandled `UnicodeEncodeError` the instant it
  tried to print one. From the API's side this just looked like an ordinary
  exit-1 script failure with a traceback that mysteriously cut off mid-frame,
  and the same exact command worked perfectly when run by hand - genuinely
  confusing until reproduced by shelling out manually. Fixed by forcing UTF-8
  on both ends of the pipe in `_run()`: `PYTHONIOENCODING`/`PYTHONUTF8` in the
  child's environment, and `encoding="utf-8"` (`errors="replace"` as a
  last-resort safety net) on the `subprocess.run()` call itself. Covered by
  `tests/test_pipeline_subprocess.py`.
- **A wrong Pokémon silently reported with misleadingly normal confidence** —
  found reviewing a real extracted event: its own `detail` text read "The
  opposing Staraptor fainted!" while its `pokemon` field said `Charizard`,
  and Staraptor wasn't anywhere in that match's actual roster.
  `build_event_prompt()`'s old roster-constraint wording told Gemini to,
  when a read was unclear, "pick the closest from these known teams" and
  "NEVER output 'unknown'" — with no distinction between a genuine fuzzy
  misread of a real roster name and a completely different species that
  isn't in the roster at all (which can happen when a match window itself
  was misdetected — e.g. a video trimmed to an arbitrary start point can
  put "match 1" over the tail end of an unrelated match). The prompt now
  explicitly separates the two cases: a plausible fuzzy match keeps normal
  confidence, but a true mismatch must still pick the closest known name
  (never "unknown" — downstream code depends on `pokemon` always being
  populated) while dropping confidence to 0.3 or lower and spelling out the
  mismatch in `detail`. That confidence drop is exactly what the
  dashboard's low-confidence "⚠ worth checking" flag (see "Data retention &
  manual corrections" above) is built to catch. Covered by
  `tests/test_build_event_prompt.py`.
- **Garbled `player_brought`/`player_lead`** (e.g. `"'hp_percent': 100} +
  Talonflame"`) — `derive_brought()` in `analyze_matches.py` assumed
  `field_state`'s `player_active`/`opponent_active` were comma-separated name
  strings; they're actually a list of `{"pokemon", "hp_percent"}` dicts. Fixed
  with a `names_of()` helper that handles both shapes; `repair_brought_leads.py`
  re-derives correct values for events.json files extracted before the fix
  (no video/Gemini re-processing needed).
- **Fake 100% Tera win rate** — `schema.json` was stale; an adapter edit had
  already removed Terastallization for this format but nobody re-ran
  `compose_schema.py`, so the AI still reported a few (hallucinated)
  `terastallized` events. `strip_illegal_events.py` removes events whose type
  isn't in the current schema. The API also now hides Tera stats entirely
  (not a 0%/fake number) whenever a format's rules say it isn't legal.
- **"Unknown" winners / fewer than 4 Pokémon detected** — some short
  (<3 min) match windows never got a result screen or a full roster read.
  `analyze_matches.py`'s `WINNER_PROMPT` now explicitly handles forfeits and
  looks at a wider post-match window (60s/12 frames, was 30s/5); the
  team-preview's own directly-read "brought 4" selection (previously fetched
  but discarded) is now merged in as a fallback when appearance-tracking
  under-counts. A `--only 3,14,20`-style flag lets you cheaply re-analyze just
  the flagged matches instead of the whole video. **Only our own team is
  required to be fully known** (`complete_data` in `/matches/summary`) — the
  opponent's reveal is a harder read and partial data there is expected, not
  flagged as broken.

## OCR accuracy tier (`--use-ocr-tier`, `analyze_matches.py`)

Built directly off the "wrong Pokémon silently reported" bug above: rather
than only mitigating that bug's symptom (the confidence-drop fix above), this
addresses its root cause by reading the battle's on-screen text banner
directly via local OCR (`ocr_battle_reader.py` + `battle_text_parser.py`)
instead of asking a vision model to re-derive exact text from a description.
A nickname on a name plate (which text alone can never resolve to a species)
is handled by `pokemon_identity.py` - a free local fuzzy-match against the
match's own known roster first, falling back to at most ONE small vision
call per distinct nickname for the whole match, cached thereafter.
`ocr_pipeline.py` merges the OCR-derived events with the existing
Gemini-derived ones, letting an OCR event win over a clearly-duplicate
Gemini one. See `ARCHITECTURE_HANDOFF.md` section 2d for the full
architecture and each module's own honestly-stated validation scope (the
bottom banner reads reliably; name plates are rougher; ability callouts near
a sprite aren't targeted yet).

**Current scope**: this is a CLI flag on `analyze_matches.py` only
(`--use-ocr-tier`, live mode, **on by default as of 2026-07-04** - pass
`--no-ocr-tier` to opt out) - it is NOT yet exposed as a toggle through the
backend job pipeline (`backend/pipeline.py`) or the dashboard's New Job
panel; a job submitted through the API runs live-mode analysis with this
tier on by default, same as a manual CLI run. Exposing an explicit
opt-out toggle through the API is a reasonable next step once this has had
real footage run through it by hand a few times (the same "your first real
run is the real test" caveat this project applies to `--use-batch-api`).

## Opponent team-preview strength (`backend/pokedex.py` + `type_synergy.py`)

Scores each opponent's brought 4 on **type-weakness overlap** — a real doubles
liability, since 2+ Pokémon sharing a weakness means one spread move or a
well-picked attacker threatens the whole side at once. It's built straight
from the standard type chart (hardcoded, works offline, no `meta_build.py` or
API key needed) and then checked against **this player's own win/loss record**
to see if it actually predicts anything — that correlation, not just the
type-chart math, is what makes it a tangible measure rather than trivia.
Extend `pokedex.SPECIES_TYPES` when a new Pokemon shows up that isn't in it.

## Accounts (Supabase)

Jobs are now owned by a real signed-in user instead of being a shared,
anyone-can-see-everything pile - this was the #1 gap flagged when this project's
own `V1_SUMMARY.md` / `PRODUCT_BRIEF.md` were written ("first 3 things to
build": accounts + a persistent data store) and it's what unblocks everything
else (real deployment, more than one person using this, data actually
surviving a restart).

**Why Supabase specifically**: it's hosted Postgres + a built-in auth system
(signup, sign-in, password resets, sessions) in one free-tier project, so this
backend never has to touch passwords or issue its own tokens - `backend/auth.py`
just asks Supabase "whose token is this" on every request. This was the
approach `PRODUCT_BRIEF.md` §10 already recommended.

### One-time project setup

1. Go to [supabase.com](https://supabase.com), sign up, and create a new
   project (pick any name/region; save the database password somewhere - you
   likely won't need it directly, but it's shown only once).
2. Wait ~2 minutes for it to finish provisioning.
3. Dashboard -> **SQL Editor** -> New query -> paste the entire contents of
   `supabase_schema.sql` (repo root of `poc-starter/`) -> Run. This creates the
   `jobs` table and its Row Level Security policies.
4. Dashboard -> **Settings -> API**. You need three values off this page:
   - **Project URL** -> `SUPABASE_URL` (backend) and `VITE_SUPABASE_URL` (frontend)
   - **anon / public key** -> `VITE_SUPABASE_ANON_KEY` (frontend only - this
     one is safe to expose in the browser bundle by design)
   - **service_role key** -> `SUPABASE_SERVICE_ROLE_KEY` (backend only -
     SECRET, never expose this to the frontend or commit it anywhere; it
     bypasses Row Level Security)
5. Copy `.env.example` -> `.env` in `poc-starter/` and fill in `GEMINI_API_KEY`,
   `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.
6. Copy `frontend/.env.example` -> `frontend/.env` and fill in
   `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`.
7. `py -m pip install -r requirements.txt` (adds `supabase` + `python-dotenv`).
8. Rebuild the frontend so it picks up the new env vars: `cd frontend && npm
   install && npm run build && cd ..`.
9. Start the backend, open the dashboard, and sign up with a real email +
   password on the login screen that now appears first.
10. Attach the seeded demo data to your new account: find your user's UUID in
    Supabase (**Authentication -> Users** -> copy the UID column), then run
    `py seed_demo_job.py --user-id <that-uuid>` from `poc-starter/`.

After that, everything works exactly like before, just per-account: every
`/jobs...` endpoint requires a valid session (the frontend attaches it
automatically once you're signed in - see `frontend/src/api.js`), and
`GET /jobs` / job lookups are always scoped to whoever's signed in.

### How it works under the hood

- **`backend/auth.py`** - `Depends(auth.current_user)` on every job-scoped
  endpoint in `main.py`. It reads the `Authorization: Bearer <token>` header,
  asks Supabase's Auth server to validate it (`client.auth.get_user(token)`),
  and returns `{id, email}` or raises 401. The backend never sees a password.
- **`backend/jobs.py`** - rewritten from an in-memory dict to real
  `select`/`insert`/`update` calls against the `jobs` Postgres table, using
  the service_role client (which bypasses RLS) - every function takes a
  `user_id` and filters by it explicitly, which is the actual access control
  (RLS in `supabase_schema.sql` is defense-in-depth in case anything ever
  queries Supabase directly from the frontend instead of through this API).
  `jobs.get_job()` returns `None` for both "doesn't exist" and "exists but
  isn't yours" - a stranger's job_id 404s exactly like a made-up one.
- **`frontend/src/lib/supabase.js`** - the browser-side Supabase client
  (anon key only). **`frontend/src/components/Auth.jsx`** - the sign-in/sign-up
  screen. **`frontend/src/api.js`** - attaches the current session's access
  token to every API call automatically.
- The pipeline scripts themselves (`analyze_matches.py` etc.) are completely
  untouched - each job still gets its own `jobs/<job_id>/` folder on disk;
  only the ownership/status metadata moved into Postgres.

### Known limitations (be aware, not yet fixed)

- No password reset flow wired up in the UI yet (Supabase supports it -
  `auth.resetPasswordForEmail()` - just not built into `Auth.jsx` yet).
- Video files still live on local disk per job folder, not object storage -
  fine for one person on one machine, not for deploying somewhere with
  multiple server instances or ephemeral disks. See "Not yet done" below.
- Email confirmation is on by default in a new Supabase project (you'll get a
  confirmation email before you can sign in) - turn it off in **Authentication
  -> Providers -> Email** while testing solo if that friction isn't wanted yet.

## Frontend (`frontend/`)

A React app (Vite + plain React, no router/state library — the whole thing is
small enough not to need one) replacing the old single-file HTML dashboard.
Same visual "job" as before (record, win rates, coaching flags, matches,
opponent intel, coach chat) reorganized into tabs, plus a new **Skill scores**
tab powered by the `skill_scores.py` progression scores that existed in the
pipeline but were never wired into the API/UI until now.

**One-time setup** (needs internet access to npm's registry — this couldn't be
run inside the sandbox that built it, so this is genuinely untested end-to-end;
if `npm run build` errors, paste the error back and it's a quick fix). Also
needs `frontend/.env` filled in first - see "Accounts" above - since the
Supabase client reads `VITE_SUPABASE_URL`/`VITE_SUPABASE_ANON_KEY` at build time:

```
cd frontend
npm install
```

**Local development** (hot-reload, calls your FastAPI server on :8000 via a
dev proxy so you don't need CORS or to rebuild on every change):

```
# terminal 1, from poc-starter/
py -m uvicorn backend.main:app --reload --port 8000

# terminal 2, from poc-starter/frontend/
npm run dev
```

Open the URL Vite prints (usually `http://127.0.0.1:5173`).

**Production build** (what you actually run day-to-day — builds static
files directly into `backend/static/`, which the FastAPI server already
serves at `/dashboard`, so there's no separate Node server to keep running):

```
cd frontend
npm run build
cd ..
py -m uvicorn backend.main:app --reload --port 8000
```

Then open `http://127.0.0.1:8000/dashboard/` as before. Re-run `npm run
build` any time you change something in `frontend/src/` — the dev server
isn't used in normal day-to-day use, only when actively editing the UI.

**Structure**: `frontend/src/App.jsx` is the orchestrator (loads the job list,
fetches all the per-job endpoints in parallel, holds the active tab).
`frontend/src/components/` has one file per dashboard section;
`frontend/src/lib/charts.jsx` has three hand-rolled SVG chart primitives
(`Bar`, `Ring`, `TrendLine`) — no charting library dependency for a project
this size. `frontend/src/api.js` is the only file that knows the backend's
URL shape.

**`NewJobPanel.jsx`** — the "+ New job" button in the header opens this
(a modal), with tabs for video URL / video upload / Showdown replay, plus
Mode (Doubles/Singles) and Regulation (M-B current / M-A launch, superseded)
dropdowns shown above the tabs regardless of source type — see
`ARCHITECTURE_HANDOFF.md` §3a. Both default to Doubles/M-B, matching the
backend's own defaults, so leaving them untouched behaves exactly like
before this feature existed. Video upload and Showdown-replay-files both
support drag-and-drop (plain HTML5 drag events, no extra dependency) with a
click-to-browse fallback. On success, `App.jsx` polls `GET /jobs/{id}` every
few seconds until the job's `done`/`failed`, showing real step progress in
the loading banner instead of a bare spinner.

**`MatchEvents.jsx`** — what a match row in the Matches tab expands into:
each event shown with its `reference_frame` thumbnail (fetched as an
authenticated blob via `api.frameBlobUrl()`, since a plain `<img src>` can't
carry a Bearer token for a private job's frame) and a "Correct this" inline
form that `PATCH`es `/jobs/{id}/events/{index}`, then reloads the dashboard.

## Not yet done

- Real job queue — job *metadata* now persists in Postgres and is scoped per
  user (see "Accounts" above), but *execution* is still a plain Python thread
  per job (`backend/jobs.py`). Fine for one person's traffic; worth swapping
  for Celery/RQ once more than one person needs to run jobs at the same time,
  since a server restart mid-run still loses that one job's progress (the row
  just sits at "running" forever until manually retried).
- Video upload streams straight to local disk — fine for a short clip, not
  realistic for a 10+ GB VOD over HTTP. The handoff's suggested stack
  (object storage + presigned upload URLs) is the real fix.
- `POST /jobs/{id}/coach` has no memory between calls (each question is
  answered fresh) — `coach_chat.py`'s interactive mode keeps history; wiring
  that through per-job would be a small follow-up.
- The opponent-strength correlation is currently based on 17 decided matches -
  a real signal worth tracking, not yet a statistically bulletproof one.
- **Per-match drill-down now exists** (`MatchEvents.jsx` - click a match row
  to expand its individual events with reference photos and inline
  correction, see "Data retention & manual corrections" above) - this closes
  the gap the previous version of this note flagged. Matches-table
  filtering/sorting is still not built, if that's wanted next.
- **The frontend additions in this pass (`NewJobPanel.jsx`, `MatchEvents.jsx`,
  the drag-and-drop upload zones, `api.js`'s new `createJob`/`correctEvent`/
  `frameBlobUrl`) were built and manually proofread for syntax, but NOT run
  through a real `npm run build`** - the environment they were built in had
  no npm registry access and a `node_modules/` already built for a different
  OS than the sandbox's Node runtime, so `vite build` couldn't execute at
  all (same class of limitation the original frontend rework note above
  already flags for npm's registry). Run `npm run build` yourself before
  relying on this - if anything doesn't compile, paste the error back.
- The frontend build was never actually run end-to-end (see "Frontend" above)
  - it's built from careful manual review, not a passing `npm run build`, so
  treat the first build as the real test.
- **The mode + regulation dropdowns added to `NewJobPanel.jsx` this pass**
  were verified with `@babel/parser` (pure JS, catches real syntax errors)
  but likewise not run through a live `npm run build` for the same
  environment reason - worth a quick look once you rebuild the frontend.
