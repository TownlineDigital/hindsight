# The Code, Explained (for people new to Python and coding)

This document walks through the *entire* current application — the video-analysis
pipeline, the web backend, the database/accounts layer, the React frontend, and the
test suite — in plain language, assuming no programming background at all. It teaches
the concepts as they come up, then explains what every file does and how all the
pieces connect.

**How to use this doc:** read Part 1 once, start to finish, even the bits that feel
obvious — later parts assume you know these words. After that, treat Parts 3–4 as a
map you come back to, not something to memorize.

---

## Part 0 — What this application actually is

Before any code: here's the whole system in one paragraph, then one diagram.

You (or eventually, many different users) paste in a link to a recorded Pokémon
match (or upload a video file). The system downloads it, figures out where each
individual match starts and ends, and then — using Google's Gemini AI, which can
"look at" images — reads each match like a person would: who's on each team, who
they picked to bring, what happened turn by turn, and who won. All of that becomes
one big structured file, `events.json`. Everything downstream (win rates, coaching
advice, progression scores, a chat you can ask questions to) is just math and text
generation performed *on top of* that one file — nothing downstream re-watches the
video.

That whole pipeline used to be something you ran yourself, one command at a time, in
a terminal. It now also has a real web application wrapped around it: a backend
server (so a browser can ask for the data over the internet instead of you reading
files by hand), a database with real user accounts (so many people can each have
their own private history), and a proper website (the "frontend") with a dashboard,
charts, and a chat box.

```
                     ┌─────────────────────────────────────────┐
                     │              THE PIPELINE                │
                     │   (video in, structured JSON/CSV out)    │
                     │                                           │
   video URL/file ──▶│ fetch_vod → structure_pass → analyze_    │
                     │ matches → battle_record/player_report/    │
                     │ coach_report → meta_build → coach_chat    │
                     └───────────────────┬───────────────────────┘
                                         │ events.json, matches.csv, etc.
                                         ▼
                     ┌─────────────────────────────────────────┐
                     │            THE BACKEND (backend/)         │
                     │  a Python web server (FastAPI) that runs  │
                     │  the pipeline as a background job and     │
                     │  serves its output as JSON over HTTP      │
                     └───────────────────┬───────────────────────┘
                                         │ HTTP requests/responses (JSON)
                                         ▼
                     ┌─────────────────────────────────────────┐
                     │           THE FRONTEND (frontend/)        │
                     │   a React website: login screen,          │
                     │   dashboard, charts, coach chat box        │
                     └─────────────────────────────────────────┘

                     ┌─────────────────────────────────────────┐
                     │   ACCOUNTS + DATABASE (Supabase/Postgres) │
                     │   who's signed in, whose job is whose —   │
                     │   or, with nothing configured, a single   │
                     │   built-in "local dev" user (see Part 3)  │
                     └─────────────────────────────────────────┘

                     ┌─────────────────────────────────────────┐
                     │              TESTS (tests/)                │
                     │  automated checks that catch real bugs    │
                     │  before a person does                      │
                     └─────────────────────────────────────────┘
```

Five "areas" of code, five sections in Part 3. Everything in this project falls into
one of them.

---

## Part 1 — The concepts you'll see (primer)

This project uses two programming languages (Python for everything server-side/data,
JavaScript for the website you look at in a browser), plus a little SQL (database
query language) and HTTP (how browsers and servers talk to each other). You don't
need to be fluent in any of them — you need to recognize what you're looking at.

### 1.1 Python basics

**Variables** hold values: `name = "Flutter Mane"`, `hp = 78`, `won = True`.

**Lists** are ordered collections in square brackets: `team = ["Incineroar", "Miraidon"]`.
You get items by position, counting from 0: `team[0]` is `"Incineroar"`.

**Dictionaries ("dicts")** are labeled collections in curly braces:
`event = {"pokemon": "Garchomp", "hp": 78}`. You get values by label:
`event["hp"]` is `78`. `event.get("hp")` does the same thing but returns `None`
instead of crashing if the label doesn't exist — you'll see `.get(...)` constantly
in this codebase specifically because AI-generated data is never 100% predictable.

**Sets** are like lists but with no order and no duplicates: `{"Mawile", "Grimmsnarl"}`.
Used whenever "did I already see this?" matters more than "what order did things
happen in" — e.g. checking species legality.

**Tuples** are like lists but can't be changed after creation, written with
parentheses: `("fire", "flying")`. Used for small, fixed groupings, like a Pokémon's
1–2 types in `pokedex.py`.

**JSON is just lists and dicts saved as text.** `events.json` is a list of dicts —
exactly the two collection types above, written to a file. That's why Python and
JSON fit together so naturally: `json.load(...)` turns file text into real Python
lists/dicts you can loop over and index into.

**Functions** are named, reusable blocks of code:
```python
def add(a, b):        # a and b are "parameters" (inputs)
    return a + b        # hands back a result to whoever called it
add(2, 3)               # calling it -> 5
```

**Default arguments** let a parameter be optional:
```python
def greet(name, greeting="Hello"):
    return f"{greeting}, {name}"
greet("Ash")                  # -> "Hello, Ash"
greet("Ash", "Hey")            # -> "Hey, Ash"
```

**`*args` and `**fields`** let a function accept a flexible number of extra
arguments. You'll see `def update_job(job_id, user_id=None, **fields):` in
`backend/jobs.py` — `**fields` scoops up *any* extra named arguments the caller
passes (`status="running", step="analyze_matches"`) into one dict, so the function
doesn't need a fixed list of every possible field up front.

**Loops** repeat: `for e in events:` runs its indented block once per item in the
list `events`. **Conditions** choose: `if winner == "player":` only runs its block
when that comparison is true; `elif` and `else` cover other cases.

**Comprehensions** build a new list/dict/set in one line instead of a full loop:
```python
names = [e["pokemon"] for e in events if e.get("pokemon")]
```
Read it right-to-left-ish: "for each `e` in `events`, if it has a `pokemon` value,
collect `e['pokemon']`." This shows up *everywhere* in this codebase once you know
to look for it — it's just a compact loop.

**Imports** borrow code someone else already wrote: `import json` loads Python's
built-in JSON toolkit; `from pathlib import Path` grabs one specific tool
(`Path`, for working with file/folder paths) out of a bigger toolkit. Libraries used
in this project: `json`, `os`, `subprocess`, `re` (pattern matching in text),
`argparse` (command-line flags), `csv`, `threading`, `uuid` (generating random unique
IDs), plus third-party ones: `google-genai` (Gemini), `fastapi` (the web server
framework), `supabase` (talking to the database/accounts service), `python-dotenv`
(loading secret keys from a file).

**f-strings** build text with values spliced in: `f"Match {i} winner: {winner}"` —
anything inside `{ }` gets evaluated and inserted as text.

**`try` / `except`** catches errors instead of crashing the whole program:
```python
try:
    risky_thing()
except Exception as e:
    print(f"that failed, but we keep going: {e}")
```
This matters enormously in this project because most of the "risky" things are
network calls (to Gemini, to the database) that can fail for reasons outside the
code's control — a good `try/except` decides "is this worth retrying, or worth
giving up on gracefully," rather than letting one bad API response kill an
hours-long video-processing job.

**`with ... as`** ("context managers") is Python's pattern for "do this, and clean
up afterward no matter what":
```python
with open("events.json") as f:
    data = json.load(f)
# the file is automatically closed here, even if json.load() had thrown an error
```

**Classes** bundle related data and behavior together, and are how Python represents
"a kind of thing." `class HTTPException(Exception):` in `backend/auth.py`'s test
stub defines a new *kind* of error. You'll mostly see classes used, not defined, in
this codebase (e.g. `FastAPI()`, `Path(...)`) — you can treat `SomeName(...)` as
"create one of these" without needing to know how the class itself works internally.

**Type hints** are optional notes about what type a value should be — Python doesn't
enforce them at runtime, but they make code much easier to read and let editors catch
mistakes early:
```python
def get_job(job_id: str, user_id: str) -> Optional[dict]:
```
Read this as: "takes a `job_id` that should be text (`str`) and a `user_id` that
should be text, and returns either a `dict` or `None` (`Optional[dict]` means
'dict, or possibly nothing')." `list[dict]` means "a list where every item is a
dict." These are documentation, not magic — nothing stops you from passing the wrong
type, but the hint tells a reader (or you, in six months) what's expected.

**Decorators** are a function that wraps another function, written with `@` right
above a `def`. You'll see this constantly in the backend:
```python
@app.get("/jobs")
def list_jobs(user: dict = Depends(auth.current_user)):
    return jobs.list_jobs(user["id"])
```
`@app.get("/jobs")` doesn't change what `list_jobs` does when you call it directly —
it registers "when a browser makes a GET request to the URL `/jobs`, run this
function and send back whatever it returns." The decorator is what turns an ordinary
Python function into a live piece of a website.

**`async def`** marks a function as one that can *pause* while waiting on something
slow (like a big file upload) and let other work happen in the meantime, then
resume. You'll see it on exactly one function in this project
(`backend/main.py`'s `create_job`, because it streams an uploaded video to disk in
chunks). You don't need to understand async deeply to read this codebase — just
recognize `async def` / `await` as "this can wait for slow things without freezing
the whole server."

### 1.2 Environment variables and `.env` files

Some values (API keys, database passwords) should never be typed directly into code
you might share or commit to a repository. The standard fix: put them in a file
called `.env` (never checked into version control — see `.gitignore`), and read them
in code via `os.environ.get("GEMINI_API_KEY")`. `python-dotenv`'s `load_dotenv(...)`
is what actually reads a `.env` file and makes its contents available through
`os.environ` — see `backend/main.py`'s very first lines.

### 1.3 A little SQL and "what is a database"

A database table is like a spreadsheet: fixed columns, one row per record. This
project has exactly one table, `jobs` (see `supabase_schema.sql`), with columns like
`job_id`, `user_id`, `status`. SQL is the language for asking a database questions:
`select * from jobs where user_id = '...'` means "give me every column, from the
jobs table, only for rows matching this user." You won't write raw SQL in this
project — `backend/jobs.py` uses a Python library (`supabase-py`) that turns method
calls like `.table("jobs").select("*").eq("user_id", user_id).execute()` into that
same SQL query behind the scenes.

**Row Level Security (RLS)** is a database-level rule ("a user can only ever select
rows where `user_id` matches their own ID") enforced by Postgres itself, as a second
layer of protection *in addition to* the same check being done in Python code. See
`supabase_schema.sql`.

### 1.4 A little HTTP and "what is a REST API"

A website talking to a server sends an **HTTP request** to a **URL**, and gets back
an HTTP **response**. Two request types matter here: **GET** (asking for data, like
loading a page) and **POST** (sending data, like submitting a form or starting a
new job). Every response has a **status code**: `200` means success, `404` means "not
found," `401` means "you're not signed in / not allowed," `500` means "the server
itself broke." You'll see these numbers throughout `backend/main.py`
(`raise HTTPException(404, ...)`) and in the frontend's error handling.

An **endpoint** is one specific URL path the server knows how to respond to, e.g.
`GET /jobs/{job_id}/record`. A backend built around a set of endpoints like this,
each returning JSON, is commonly called a **REST API** — which is all `backend/`
is.

### 1.5 JavaScript and React (the frontend)

The frontend is written in a different language, JavaScript (specifically a
flavor called JSX, explained below), because that's what runs inside a web browser.

**Variables**: `let x = 5;` (can change later) or `const y = "Ash";` (can't be
reassigned — use this by default). **Arrow functions** are JavaScript's compact
function syntax: `(a, b) => a + b` means the same thing as a Python
`def f(a, b): return a + b`.

**Template literals** are JavaScript's f-strings, using backticks:
`` `Match ${i} winner: ${winner}` ``.

**Arrays** are JavaScript's lists: `const team = ["Incineroar", "Miraidon"];`.
**Objects** are JavaScript's dicts: `const event = {pokemon: "Garchomp", hp: 78};`,
read with `event.hp` or `event["hp"]`.

**Array methods** (`.map`, `.filter`, `.sort`) are JavaScript's comprehensions —
`matches.filter(m => m.winner === "player")` means "keep only the items where this
condition is true," exactly like a Python list comprehension's `if` clause.

**JSX** is HTML-looking markup written directly inside JavaScript code — this is
what every file ending in `.jsx` in `frontend/src/` is full of:
```jsx
function Greeting({ name }) {
  return <h1>Hello, {name}</h1>;
}
```
This looks like it's mixing two languages because it is — JSX gets converted into
plain JavaScript before it runs (that conversion is what the "build" step, `npm run
build`, does). Anything inside `{ }` within JSX is regular JavaScript being evaluated
and inserted, same idea as an f-string.

**React components** are just JavaScript functions that return JSX — a description
of what should appear on screen. `frontend/src/components/RecordCards.jsx` exports
a function `RecordCards` that takes some data and returns the markup for the record
cards section.

**Props** are a component's inputs, passed like HTML attributes:
`<RecordCards record={data.record} report={data.report} />` — inside the function,
these arrive bundled as one object, usually destructured:
`function RecordCards({ record, report }) { ... }`.

**State** is data a component remembers and can change over time, declared with
React's `useState`:
```jsx
const [count, setCount] = useState(0);   // count starts at 0
setCount(count + 1);                       // updates it, and React redraws the screen
```
`useState` always returns a pair: the current value, and a function to change it.
Whenever that setter function is called, React automatically re-runs the component
and updates what's on screen — you never manually touch the page's HTML.

**Effects** (`useEffect`) run some code in reaction to a component appearing on
screen, or a particular value changing:
```jsx
useEffect(() => {
  api.listJobs().then(setJobs);
}, []);   // the empty [] means "run this once, when the component first appears"
```
This is the standard pattern for "fetch data from the server when the page loads" —
you'll see it in almost every component that needs backend data.

**Hooks** is the umbrella term for special functions like `useState`/`useEffect` that
only work inside a component and let it "hook into" React's rendering and lifecycle.

---

## Part 2 — Patterns that repeat throughout this codebase

Once you spot these, most files stop looking unique and start looking like
variations on a theme.

1. **Command-line flags (`argparse`).** Every standalone script (`analyze_matches.py`,
   `structure_pass.py`, ...) accepts `--flag value` options from
   `ap.add_argument("--model", default="gemini-2.5-flash")`-style declarations. This
   lets you change behavior without editing code.

2. **Reading/writing JSON.** `json.load(open("events.json"))` turns a file into
   Python lists/dicts; `json.dump(data, open("out.json", "w"))` saves them back.
   The entire pipeline's "database" is just JSON/CSV files on disk.

3. **Running FFmpeg via `subprocess`.** FFmpeg is a separate video-processing
   program, not Python code. `subprocess.run([...])` runs it with a list of
   command-line arguments — "take this video, grab one frame every N seconds,
   shrink to some width, save as JPGs."

4. **Calling Gemini.** A small `call(...)` function (in `analyze_matches.py`) packs
   a text prompt plus some images and sends them to Gemini, then parses the JSON it
   sends back. Every "AI reads this" step in the whole project flows through this
   one function, including its retry logic (see below).

5. **Retry-with-backoff.** Network calls fail sometimes for reasons that have
   nothing to do with your code (the API is briefly overloaded). The fix pattern,
   used in `analyze_matches.py`'s `call()`: try, and if it's a *known transient*
   error, wait a bit and try again, waiting longer each time ("exponential
   backoff": 5s, 10s, 20s...) — but only a few times, then give up and let the
   caller decide what to do.

6. **Doing many things at once (concurrency).** Sending API requests one at a time
   is slow. `concurrent.futures.ThreadPoolExecutor` fires several off in parallel —
   like opening multiple checkout lanes instead of one — used when processing many
   batches of frames within a single match.

7. **One shared client, reused.** Creating a fresh connection to an external service
   (Gemini, Supabase) for every single request is wasteful. The pattern in
   `backend/auth.py`: a module-level variable starts as `None`; the first call
   creates the real connection and saves it there; every later call reuses the same
   one. This is sometimes called a "singleton."

8. **Graceful degradation via a config check.** `backend/auth.py`'s `configured()`
   function is checked before doing anything Supabase-specific; when it's `False`
   (no `.env` filled in), the code takes a simpler fallback path (a single local
   user, an in-memory dict) instead of crashing. The same *shape* of check appears
   for whether a format allows Terastallization (`backend/analytics.py`) — "check a
   condition once, branch cleanly, never assume."

9. **The FastAPI endpoint pattern.** Every URL the backend serves follows the same
   shape: a decorator declares the HTTP method and path
   (`@app.get("/jobs/{job_id}")`), the function's parameters describe what it needs
   (a path variable, a login dependency), and whatever it `return`s gets
   automatically converted to JSON for the response.

10. **Dependency injection (`Depends`).** `user: dict = Depends(auth.current_user)`
    tells FastAPI "before running this endpoint, run `auth.current_user` first, and
    hand me its result as `user`." This is how every job-related endpoint knows who's
    asking without repeating the same login-check code in every single function.

11. **"One source of truth."** `backend/analytics.py` doesn't recompute win rates
    from scratch — it imports and calls the exact same functions
    (`coach_report.per_match`, etc.) that the original command-line reports use, so
    the website and the `.md` reports can never quietly disagree about what a "win"
    is.

12. **The React data-fetching pattern.** A component's `useEffect` calls an `async`
    function that `await`s a `fetch(...)` call to the backend, then calls a
    `useState` setter with the result — see `frontend/src/App.jsx`'s `loadDashboard`.
    Errors are caught and stored in their own state variable so the screen can show
    a clear message instead of a blank page.

13. **Automated tests as executable proof.** Instead of "I read the code and it
    looks right," a test *runs* the real function with known input and checks the
    real output with `self.assertEqual(...)`. See Part 3's `tests/` section, and
    Part 5 for how to run them yourself.

---

## Part 3 — Every file, what it does

### 3.1 The pipeline (root-level Python scripts) — video in, structured data out

These are meant to be run in order, either by hand or via `run_full.py`/the backend.

**`fetch_vod.py`** — Downloads a Twitch/YouTube VOD. `download()` hands a URL to the
`yt-dlp` library and saves it as a fixed filename (`vod.mp4`) so spaces or special
characters in a stream's title never cause problems later.

**`compose_schema.py`** — Builds `schema.json`, the literal instructions the AI
follows, by merging three small JSON files: `adapters/_core.json` (universal,
game-agnostic concepts), a game file (`adapters/pokemon/game.json` — Pokémon's
vocabulary), and a mode file (`adapters/pokemon/doubles.json` — doubles-specific
rules, like "2 active Pokémon per side"). `compose()` does the merging: combine
event-type lists, stack the "notes" text, carry over the format's legal-mechanics
`rules`. This structure (see `ADDING_A_NEW_GAME.md`) is *why* onboarding a new game
is "write two JSON files," not "rewrite the extraction code."

**`structure_pass.py`** — Finds every match's start/end time in the raw video.
`sample_frames()` uses FFmpeg to grab one small frame every ~10 seconds (cheap: only
this many images need reading, not the whole video). `classify()` asks a cheap
Gemini model an easy, reliable question per frame: "battle, menu, team_preview, or
result?" `segment_matches()` groups consecutive "battle" frames into one match
(a real battle lasts minutes, so a few seconds of overlay/lag can't split it into
two by mistake). Writes `matches.csv` (`match, start_seconds, end_seconds,
duration_seconds`).

**`analyze_matches.py`** — The heart of the whole system, and the file that's been
modified most during this project's development (see the "Known bugs fixed here"
box below). Before the per-match loop, `main()` calls `configure_regulation(args.adapters,
args.regulation)`, which reassigns the module-level `ALLOWED_SPECIES`/`_ALLOWED_NORM`
allowlist to whichever regulation (`--regulation`, default `m-b`) was requested — loaded
from `adapters/pokemon/regulations/<id>.json` (see `ARCHITECTURE_HANDOFF.md` §3a). If
nothing ever calls it, `ALLOWED_SPECIES` falls back to a hardcoded constant identical to
`m-b.json`'s own species list, so this is purely additive. For each match window,
`main()`'s loop:
1. Calls `read_roster()`, which samples team-preview frames and asks Gemini
   (`build_roster_prompt(rules)`, built fresh per job from the composed schema's
   `rules` — doubles asks for a "pick 4 of 6" selection, singles doesn't, since it has no
   such step) to read both full 6-Pokémon teams and (doubles only) each side's chosen 4.
   If the first attempt comes back suspiciously sparse (fewer than
   `ROSTER_MIN_ACCEPTABLE`), it automatically retries with a wider, earlier,
   denser set of frames before giving up — see `ROSTER_SEARCH_ATTEMPTS`.
2. Runs every read species name through `reject_banned_species()`, which checks
   each one against `ALLOWED_SPECIES` (an **allowlist** — the Pokémon actually legal
   under the currently-configured regulation — not a blocklist of everything banned,
   since the banned list is effectively infinite). `_species_base_norm()` strips Mega
   Evolution and regional-form annotations first, so "Mega Mawile" and "Mawile
   (Mega)" are recognized as the same underlying species for both the legality
   check and Species Clause (no duplicate species on one team) deduplication.
3. Samples dense battle frames and, for each batch, `build_event_prompt()` builds
   instructions that include the *already-known* rosters (so the AI is
   constrained to real possibilities instead of guessing), and `call()` sends
   them to Gemini. `parse_events()` normalizes whatever JSON shape comes back.
4. `derive_brought()` figures out each side's actual chosen 4 by watching which
   Pokémon actually appeared during the match, matched against the known roster —
   more reliable than trusting a single read of the selection screen alone.
5. Calls `read_winner()` for the result screen, with the same
   wider-window-on-a-vague-answer retry pattern as the roster read.
6. `attach_reference_frames()` tags every event with the path of whichever
   sampled battle frame was closest to it in time (`reference_frame`).
7. *(only with `--use-ocr-tier`)* `ocr_pipeline.extract_ocr_events()` samples
   the SAME match window a second time, at higher resolution, and reads the
   on-screen battle-text banner directly via OCR (`ocr_battle_reader.py` +
   `battle_text_parser.py`) instead of asking Gemini to describe text that's
   already exactly on screen. Any Pokémon nickname it encounters is resolved
   via `pokemon_identity.py` (free fuzzy-match against the known roster
   first, at most one small vision call per distinct nickname otherwise).
   `merge_ocr_and_vision_events()` then folds these in, letting a
   deterministic OCR event win over a Gemini event that clearly duplicates
   it. See `ARCHITECTURE_HANDOFF.md` section 2d.
8. `prune_unreferenced_frames()` deletes everything else in that match's
   frame folder — roster-preview frames, winner-read frames, and every
   battle frame that *wasn't* picked as a reference. This runs per match
   (not once at the very end) specifically so a match's frame folder never
   balloons to hundreds of images that nothing ever points at; see
   `ARCHITECTURE_HANDOFF.md` section 2c for why that mattered in practice
   (an unbounded `match_frames/` tree made `uvicorn --reload`'s file watcher
   slow enough to make the dashboard stop responding).
9. `save_outputs()` writes `events.json`/`events.csv` after *every single match*,
   not just at the end — so a crash partway through a long video never loses
   already-processed matches.

   A **circuit breaker** (`MAX_CONSECUTIVE_FAILURES`) stops the whole run early,
   with a clear message, if several matches in a row fail completely — a sign of a
   real API outage, not worth grinding through the rest of the video producing
   garbage.

**`transcribe.py`** — Turns the commentary audio into text with timestamps.
`extract_audio()` (FFmpeg) pulls the audio track; `transcribe_file()` runs Whisper
(a speech-to-text AI model) to produce `transcript.json`.

> **Known bugs fixed in `analyze_matches.py` (a real example of iterative
> debugging):** an early version used a hand-maintained *blocklist* of banned
> Pokémon, which is fundamentally unwinnable (the list of things NOT in a small
> closed roster is huge and always growing) — replaced with the allowlist
> approach above. Regional forms like "Alolan Ninetales" were initially rejected
> because only the suffix spelling ("Ninetales-Alola") was recognized, not the
> prefix spelling. A roster read containing a literal `None` value once crashed
> `sorted()` deep inside `reject_banned_species` because you can't compare `None`
> to text in Python — fixed by filtering blanks out first. Every one of these has
> a matching automated test in `tests/test_species_legality.py` now, specifically
> so they can never silently come back. A fourth, found later during real
> end-to-end dashboard testing: `build_event_prompt()`'s roster-constraint
> wording used to say "pick the closest from known teams, NEVER output
> 'unknown'" with no distinction between a genuine fuzzy misread and a
> Pokémon that isn't in the roster at all — a real extracted event's own
> `detail` text said "Staraptor fainted" while its `pokemon` field said
> "Charizard" (Staraptor wasn't in that match's roster), both reported at a
> confidence that looked no different from a normal, reliable read. Fixed by
> telling the model explicitly to drop confidence to 0.3 or lower and state
> the mismatch in `detail` when what it read doesn't match the roster at
> all — covered by `tests/test_build_event_prompt.py`, and directly what the
> dashboard's low-confidence "⚠ worth checking" flag is designed to catch.
> That same Staraptor/Charizard bug is also what motivated `--use-ocr-tier`
> (`ocr_pipeline.py`, `ocr_battle_reader.py`, `battle_text_parser.py`,
> `pokemon_identity.py`) — rather than only flagging a bad vision-model
> guess after the fact, it reads the battle's on-screen text banner
> directly via local OCR, which is deterministic where a vision read is
> only probabilistic. See step 7 above and `ARCHITECTURE_HANDOFF.md`
> section 2d for the full design and its honestly-stated current limits.

**`showdown_import.py`** — A second, completely different way to produce
`events.json`: instead of a video + Gemini, it reads a Pokémon Showdown
replay (a saved `.html` page, a saved `.json` file, or a live replay URL) and
parses Showdown's own battle log directly — a documented, line-based
protocol (`|move|...`, `|switch|...`, `|win|...`) that's a complete, EXACT
record of the match, no AI guessing involved at all. `extract_log_text()`
finds the actual log text regardless of whether the source is raw JSON, a
JSON blob embedded in an HTML page, or plain pasted log text — it tries each
shape in turn rather than assuming one exact format, the same
don't-be-brittle philosophy as the video pipeline's roster/winner retries.
`BattleParser` walks the log line by line, tracking which species currently
occupies each board position (updated on every switch) so it can resolve
bare position references like `p1a: Salazzle` in later lines. It calls the
exact same `analyze_matches.reject_banned_species()` and
`analyze_matches.derive_brought()` the video pipeline uses — one set of
legality/brought-4 rules, whichever source produced the match. Since
Showdown enforces format legality server-side, a real ladder replay should
*always* pass the legality check cleanly; if it doesn't, that's a sign this
project's own `ALLOWED_SPECIES` list is stale, not that the replay is wrong.
Both this script and `analyze_matches.py` write the identical `events.json`
shape, so every downstream tool (the analytics scripts below, the whole
dashboard) works on Showdown-sourced matches with zero changes — verified in
`tests/test_showdown_import.py` against a real, public replay.

**`frame_dedup.py`, `gemini_batch.py`, `compare_classifier_models.py`** —
Three cost/accuracy tools built after a real conversation about Gemini API
spend, each independent and stackable (see `ARCHITECTURE_HANDOFF.md` section
2b for the full writeup):

- `frame_dedup.py`'s `dedupe_frames()` shrinks a grayscale copy of each
  battle frame to a tiny 64x64 image and measures how different it is from
  the last frame it *kept* (not just the last frame it saw — that distinction
  matters for correctly collapsing a long static screen to one kept frame
  while still catching slow visual drift). A near-duplicate frame can't show
  a new event the last kept one didn't already show, so skipping it costs
  nothing but the API call. It's free, local, and runs before any frame is
  ever sent to Gemini — on by default in `analyze_matches.py`.
- `compare_classifier_models.py`'s `compare()` runs the exact same sampled
  frames through two different models (default: Gemini 2.5 Flash vs. the
  much cheaper Flash-Lite) and reports an agreement rate plus every
  timestamp they disagreed on, so switching `structure_pass.py` to a cheaper
  model is a measured decision instead of a guess.
- `gemini_batch.py` reroutes the bulk battle-frame event extraction — the
  single biggest cost driver — through Gemini's Batch API: half price for
  the exact same model and output, at the cost of not being instant. It's
  split into pure logic (`encode_key`/`decode_key`/`build_request_line`/
  `parse_result_line` — fully tested, no network needed) and orchestration
  (`submit_battle_batch`/`wait_for_batch`/`collect_battle_batch_results` —
  the real `client.files`/`client.batches` calls, tested here only against a
  fake stub client since no live API key was available while building it).
  Wired into `analyze_matches.py` via `--use-batch-api`, with job state
  saved to disk before waiting so a closed terminal doesn't lose the run —
  resumable with `--resume-batch-job`.

### 3.2 The analytics scripts — pure math over `events.json`, no AI involved

**`battle_record.py`** — Counts wins/losses. `matches_from_previews()` splits the
flat events list into per-match groups by watching for `team_preview` markers, then
reads each match's `battle_end` winner.

**`player_report.py`** — Usage statistics. Uses `collections.Counter` (a
dictionary specialized for counting things) to tally most-brought Pokémon, most
common leads, and most-used moves, plus KO differential.

**`coach_report.py`** — The coaching layer. `per_match()` summarizes one match's
outcome/lead/brought/KOs into a clean dict; `winrate_table()` computes win rate
grouped by any key (lead, bring, opponent Pokémon); then a set of rules turns
patterns into plain-English flags (predictable leads, a specific Pokémon that's
losing more than it should, a game lost after being ahead — a likely "throw").

**`skill_scores.py`** — Computes the four 0–100 progression scores (Tempo,
Adaptability, Execution, Closing) and a confidence tier based on how many matches
back them up. `compute_skill_scores(events)` is the importable core (used by
`backend/analytics.py`); the scores are explicitly documented as *heuristic
anchors*, meant to be recalibrated against real population data once enough
different people have used the app.

**`meta_build.py`** — Builds the knowledge base the AI coach draws on.
`fetch_type_chart()`/`fetch_pokedex()` pull static game-mechanics data (type
matchups, Pokémon types) from the free public PokeAPI. `own_meta()` computes *your
own* usage/win-rate stats from `events.json`. Both get combined with the format's
legal-mechanics `rules` (from `schema.json`) into `meta/<format>.json`.

**`coach_chat.py`** — The conversational AI coach. `profile_summary()` and
`load_meta_context()` assemble everything the AI is allowed to reference (your
stats, the format's legal rules, the meta knowledge base) so its advice is both
relevant and legal. `match_block()` pulls one specific match's full detail when a
question seems to be about it. `answer()` sends all of that context plus your
actual question to Gemini and returns its reply.

**`repair_brought_leads.py`** — A one-time fix-up script: re-derives correct
`player_brought`/`player_lead` values for an `events.json` file that was produced
*before* a bug fix, without needing to re-run the (expensive) video analysis.

**`strip_illegal_events.py`** — Removes any event from `events.json` whose `event`
type isn't in the *current* `schema.json` — used once to clean out fake
`terastallized` events that were generated back when the schema still allowed
them, before Champions' no-Terastallization rule was correctly configured.

**`grade_matches.py`** — The human-in-the-loop accuracy-checking tool (see
`tests/README.md` for the full explanation). For a given list of match numbers, it
re-extracts the exact frames the AI used for the roster/winner reads into a
`grading/` folder for a person to look at, and writes what the system currently
believes into `grade_accuracy.csv` with blank columns for a human to fill in the
*actual* correct answer after looking. `upsert_grade_rows()` merges new rows in
without disturbing previously hand-graded ones for other matches — a real bug (a
text-vs-number type mismatch that silently duplicated rows instead of replacing
them) was caught and fixed here, and is now guarded by
`tests/test_grade_matches.py`.

**`seed_demo_job.py`** — Copies the root-level `events.json`/`matches.csv`/etc.
(from an earlier full pipeline run) into `jobs/demo/`, and — when Supabase
accounts are configured — registers that folder as a real job owned by whichever
user ID you pass with `--user-id`, so a fresh account has real data to look at
immediately instead of an empty dashboard.

**`run_full.py`** — Runs steps 0–7 of the *current* match-aware pipeline in order,
stopping and reporting which one failed if something goes wrong. This is exactly
what `backend/pipeline.py` also does, just as a background job instead of a
one-off terminal command — the two are meant to stay in sync.

**`run_all.py`** / **`0_prefilter.py`** / **`1_extract_frames.py`** /
**`2_analyze_gemini.py`** / **`3_read_ocr.py`** — The *original*, simpler
proof-of-concept pipeline from before match-aware analysis existed (single-pass
frame extraction + Gemini read, no per-match roster/winner logic, optional OCR for
exact on-screen numbers). Kept for reference and for genuinely simple/short clips;
`run_full.py`/`analyze_matches.py` are what the real app actually uses today.

### 3.3 `adapters/` and `schema.json` — the "vocabulary" layer

`adapters/_core.json` defines universal, game-agnostic concepts (every game has
*some* notion of a "match ending," for instance) and must never be edited just to
fit one game. `adapters/pokemon/game.json` defines Pokémon's own vocabulary
(event types like `move_used`, `pokemon_fainted`) and maps each one back to a core
concept. `adapters/pokemon/doubles.json` (and `singles.json`) add only what's
*different* about that specific mode — active-Pokémon count, win condition,
worked examples, and the `rules` block (legal mechanics, current regulation,
banned-species categories) that both `analyze_matches.py` and the AI coach read.
`compose_schema.py` merges all of this into `schema.json`, the file the extraction
prompts actually consult. See `ADDING_A_NEW_GAME.md` for the full guide to adding
another game this way.

### 3.4 `backend/` — the web server (FastAPI)

This turns the pipeline above into an actual website's backend: a running program
that listens for HTTP requests and answers them with JSON.

**`backend/main.py`** — Defines every URL ("endpoint") the server responds to.
Loads `.env` right at the top (before anything else needs those values), then
declares the FastAPI `app` and every route as a decorated function (see Part 2,
pattern 9). Endpoints include `POST /jobs` (start a new analysis), `GET /jobs`
(list your jobs), `GET /jobs/{id}/record` / `/report` / `/skill-scores` /
`/matches/summary` / `/opponent-strength` (all the dashboard's data), `POST
/jobs/{id}/coach` (ask the AI coach a question), and `GET /auth/status` (tells the
frontend whether real sign-in is required or it's running in local dev mode).
Also mounts the built React app (`backend/static/`) at `/dashboard`.

**`backend/jobs.py`** — The "job store": everything about creating, updating,
fetching, and listing analysis jobs, scoped to whichever user owns them. In real
mode, every function talks to the `jobs` table in Postgres via the Supabase
client. In **local dev mode** (see `auth.configured()`), the exact same functions
instead use a plain Python dictionary in memory, plus `_local_discover()`, which
picks up any `jobs/<id>/` folder that already has an `events.json` in it (like the
seeded demo job) automatically — this is what lets the whole app run and be
checked with zero cloud setup.

**`backend/auth.py`** — Turns a login token (sent by the frontend as an
`Authorization: Bearer <token>` header after a real Supabase sign-in) into a real
user's ID, by asking Supabase's own authentication server to validate it. Also
defines `LOCAL_USER` and `configured()` — when Supabase credentials aren't set at
all, `current_user()` (the function every protected endpoint depends on) simply
returns `LOCAL_USER` without requiring any token, which is the other half of local
dev mode.

**`backend/analytics.py`** — Turns raw `events.json` into the exact JSON shapes
the dashboard needs: `compute_record` (wins/losses/win-rate tables),
`compute_match_list` (one clean row per match with ⚠/🚫-worthy flags precomputed),
`compute_report` (combat stats, Tera stats — hidden entirely, not faked, when a
format doesn't have Terastallization — toughest matchups, coaching flags),
`compute_opponent_strength` (calls into `type_synergy.py`), and
`compute_skill_scores` (a thin wrapper around `skill_scores.py`, so the "why" of
those four numbers lives in one place). Deliberately imports and reuses the same
functions the command-line `.md` reports use (Part 2, pattern 11) instead of
recalculating anything from scratch.

**`backend/pipeline.py`** — Runs the actual analysis scripts for one job, each as
a separate subprocess (a completely separate running copy of Python) rather than
importing them directly. `_run()` is the one place that invokes each script;
`run_full_pipeline()` calls it once per stage (`get_video`, `compose_schema`,
`structure_pass`, `analyze_matches`, `battle_record`, `player_report`,
`coach_report`, `transcribe`), reporting progress after each. Running each job in
its *own* folder as a subprocess is what lets every script keep writing to a fixed
filename like `events.json` without different jobs' files colliding, and means a
crash in one job's video processing can never take down the whole web server.
There's a second entry point now, `run_showdown_pipeline()` — the Showdown-replay
path (`source_type="showdown"` on `POST /jobs`), running a shorter step list
(`STEPS_SHOWDOWN`: `get_replays`, `compose_schema`, then the same three
pure-analytics steps) with no video/FFmpeg/Gemini call anywhere in it. It calls
`showdown_import.py --files`/`--urls` against whatever the API endpoint already
saved into the job folder (`replay0.html`, `replay1.json`, ... or a
`replay_urls.txt`), then everything after that is identical to the video path
because `events.json`'s shape doesn't care which pipeline produced it.
`total_steps_for(source_type)` is what lets `GET /jobs/{id}` report the right
step count either way. Neither pipeline function deletes its frame folders
anymore (that cleanup used to run at the very end of `run_full_pipeline()`) -
every event's `reference_frame` path (see `analyze_matches.attach_reference_frames`)
needs to keep pointing at a real file for the dashboard's Matches-tab
thumbnails/corrections to keep working.

**`backend/job_files.py`** — Two small, deliberately dependency-free (no
fastapi/supabase import) file helpers `backend/main.py` uses:
`safe_frame_path()` is the actual security check behind `GET
/jobs/{id}/frame/{path}` - resolves a requested path against one job's own
folder and raises if it would escape it (path traversal), pulled out into
its own function specifically so it's unit-testable without a running
FastAPI app. `save_events()` writes `events.json`/`events.csv` at an
explicit absolute path (unlike `analyze_matches.save_outputs()`, which
assumes the process's current folder IS the job's folder - true when a
pipeline script runs as a subprocess, not true inside the always-running
FastAPI server).

**`backend/audit.py`** — An internal (not user-facing - no endpoint reads
it) audit trail: `record(event_type, **fields)` appends one line to
`audit_log.jsonl` and, whenever Supabase is configured, also inserts into a
service-role-only `audit_log` table. Records job lifecycle
(`job_created`/`job_step`/`job_completed`/`job_failed`, called from
`backend/jobs.py`) and manual event corrections (`event_corrected`, called
from `backend/main.py`'s `PATCH /jobs/{id}/events/{index}`). Deliberately
fails soft - if writing an audit line itself errors, that's logged and
swallowed, never allowed to break the real job the user is waiting on.

**`backend/pokedex.py`** — Static reference data: the 18-type damage-effectiveness
chart (hasn't changed since Fairy was added years ago, so it's safe to hardcode)
and a lookup of species → their type(s), for the Pokémon that have actually shown
up in this project's matches so far. `type_multiplier()`/`weaknesses()` are the
small pure-math functions built on top of it.

**`backend/type_synergy.py`** — Scores a brought-4 team on shared-weakness
overlap: a real doubles team-building liability, since two Pokémon weak to the
same type both go down to one well-placed attack. `team_risk()` is the one public
function — it explicitly reports species it doesn't recognize as "unresolved"
rather than silently guessing.

**`backend/models.py`** — Defines the exact *shape* of a few request/response
JSON bodies using Pydantic (a library FastAPI is built on). `JobStatus`,
`CoachQuestion`, `CoachAnswer`, `EventCorrection` (the `{fields: {...}}` body
for `PATCH /jobs/{id}/events/{index}` - deliberately just a freeform dict,
since events themselves have no fixed schema) — each field, its type, and
whether it's optional. FastAPI uses these to auto-validate incoming requests
and auto-generate the `/docs` interactive API page.

**`backend/static/`** — Where the *built* React frontend lives after `npm run
build` — plain HTML/CSS/JS files a browser can run directly, generated from
`frontend/src/`. **`backend/static_legacy/`** keeps a copy of the original
hand-written single-file HTML dashboard, from before the React rework, in case
it's ever useful to compare against.

### 3.5 `frontend/` — the website (React + Vite)

**`frontend/index.html`** — The one real HTML file; almost empty, just a `<div
id="root">` that React will fill in, and a `<script>` tag loading the actual app.

**`frontend/src/main.jsx`** — The entry point: finds that `<div id="root">` and
tells React to render the `<App />` component into it.

**`frontend/src/App.jsx`** — The orchestrator. Holds the top-level state: which
job is selected, which tab is active, the loaded dashboard data, loading/error
status. Its `useEffect`s (Part 1.5) do, in order: (1) ask the backend `GET
/auth/status` to find out whether sign-in is required at all; (2) if it is,
listen for Supabase's own sign-in/sign-out events; (3) once either "signed in" or
"local dev mode, no sign-in needed" is true, load the job list and the selected
job's dashboard data. Renders either a "Checking..." message, the `<Auth />`
sign-in screen, or the full dashboard depending on that state.

**`frontend/src/api.js`** — The *only* file that knows the backend's URL shape.
Every other component calls a function here (`api.record(jobId)`, `api.askCoach(...)`)
instead of writing `fetch(...)` calls directly. `authHeader()` automatically
attaches the current Supabase session's token to every request (or nothing at all,
in local dev mode, where `supabase` is `null` — see below). `api.createJob(formData)`
posts a new job (video or Showdown); `api.correctEvent(jobId, index, fields)` PATCHes
one event; `api.frameBlobUrl(jobId, framePath)` is the odd one out — it can't reuse
the normal JSON helper, since a reference-frame image needs `fetch().blob()` instead
of `.json()`, and returns a `blob:` object URL an `<img>` tag can point at (a plain
`<img src="/jobs/.../frame/...">` can't carry the Authorization header a private job's
frame needs, so the bytes have to be fetched manually first).

**`frontend/src/lib/supabase.js`** — Creates the browser-side Supabase client
using two "public/safe to expose" values (`VITE_SUPABASE_URL`,
`VITE_SUPABASE_ANON_KEY`) read from `frontend/.env`. If those aren't set, exports
`null` instead of crashing, so the rest of the app can cleanly detect "local dev
mode, skip all of this."

**`frontend/src/lib/charts.jsx`** — Three small, hand-built SVG chart components
(`Bar`, `Ring`, `TrendLine`) with no external charting library dependency — SVG
(Scalable Vector Graphics) is just XML-like markup for drawing shapes, and React
can generate it exactly like any other JSX.

**`frontend/src/lib/format.js`** — Small formatting helpers with no UI of their
own: `pctClass`/`scoreClass` decide whether a number should be styled green/
yellow/red, `formatDuration` turns seconds into `m:ss`.

**`frontend/src/components/*.jsx`** — One file per dashboard section, each a
function taking the relevant slice of data as props and returning JSX:
`Header` (job picker, tab navigation, sign-out, the "+ New job" button),
`Auth` (the login/signup form, calling `supabase.auth.signInWithPassword`/
`signUp` directly), `RecordCards` (win rate, trend line, combat stats),
`SkillScores` (the four progression bars + overall ring), `CoachingFlags`
(the plain-English flags list), `StatTable` (`WinRateTable`/`CountTable`,
reusable table-with-inline-bar components), `MatchesTable` (the per-match
table with ⚠/🚫 badges — clicking a row expands it via `MatchEvents`),
`OpponentStrength` (the type-overlap-risk section), `CoachChat` (the chat
box, calling `api.askCoach`).

**`frontend/src/components/NewJobPanel.jsx`** — The modal the header's "+
New job" button opens: tabs for video URL / video upload / Showdown replay,
each building a `FormData` and calling `api.createJob()`. Its inner
`DropZone` component is a small, dependency-free drag-and-drop file zone
(plain `onDragOver`/`onDrop` handlers, no library) reused for both the
single video-file case and the multi-file Showdown-replay case via a
`multiple` prop — clicking it also falls back to a normal file picker.

**`frontend/src/components/MatchEvents.jsx`** — What a `MatchesTable` row
expands into: every event belonging to that match, each showing its
`reference_frame` as a thumbnail (`EventThumb`, which fetches the image as
an authenticated blob via `api.frameBlobUrl` and revokes the object URL on
cleanup so thumbnails don't leak memory) and a "Correct this" button that
opens a small per-field edit form, saving via `api.correctEvent()`. Tracks
`__idx` — the event's position in the FULL (unfiltered) events array — since
that's what `PATCH /jobs/{id}/events/{index}` actually addresses, not the
position within just this one match's filtered list.

Added after real end-to-end testing surfaced a genuinely confusing misread
(an opponent Pokémon reported as "Charizard" while the event's own reasoning
text said "Staraptor fainted" — a name-canonicalization mismatch) with no
easy way to spot it: `confidenceBadge()` turns the `confidence` field
(previously hidden from the UI entirely) into a color-coded percentage
badge, any event below `LOW_CONFIDENCE_THRESHOLD` (0.9) gets an automatic
"⚠ worth checking" flag plus a warn-colored left border, and the `detail`
field (the AI's own stated reasoning) gets pulled out of the plain
key/value list into its own highlighted "AI's reasoning" block instead of
blending in with every other field. `ImageLightbox` makes the thumbnail
click-to-enlarge (reuses the New Job panel's `.modal`/`.modal-backdrop`
scaffolding, just wider) since judging whether a read actually matches the
screen — a health bar, on-screen text — needs more than a 96x54 thumbnail.
`team_preview` is now pulled out of the flat per-match list into its own
labeled "Team Preview" section (still the same `EventRow`, same correction
form — just visually separated) since it used to sort first in the list
with no distinguishing header and was easy to scroll past without
recognizing it.

**`frontend/vite.config.js`** — Configuration for Vite, the tool that turns
`frontend/src/`'s JSX/JS into the plain files a browser can run. `base:
"/dashboard/"` matches where FastAPI serves the built app from; the `server.proxy`
section is what lets `npm run dev` (a live-reloading local development server)
forward API calls to the real backend on port 8000 without hitting
cross-origin-request errors.

**`frontend/package.json`** — The Node.js/npm equivalent of `requirements.txt`:
lists exactly which packages this app depends on (`react`, `vite`,
`@supabase/supabase-js`) and defines the `npm run dev`/`build`/`preview` shortcut
commands.

### 3.6 `tests/` — automated proof things still work

**`tests/test_species_legality.py`** — Tests the allowlist and Mega/regional-form
normalization in `analyze_matches.py`. Every single test here is written against a
*real bug that actually happened* during this project (see the box in 3.1) —
that's deliberate: a test that guards a real, previously-shipped mistake is far
more valuable than a test that only checks something that was never actually
wrong.

**`tests/test_analytics.py`** — Tests `backend/analytics.py` against the real
seeded demo data, checking *invariants* ("wins + losses always equals matches,"
"a percentage is always between 0 and 100") rather than one specific hardcoded
number, so these don't break every time the underlying data legitimately changes
(e.g. after fixing a roster-read bug and re-running).

**`tests/test_skill_scores.py`** — Tests `skill_scores.py`'s *behavior*
("a dominant win-loss record scores higher Tempo than a struggling one") instead
of pinning an exact score, because the scores are explicitly documented as
heuristics still being calibrated — a test that says "score must equal 64.3
forever" would break on every legitimate recalibration.

**`tests/test_grade_matches.py`** — Tests `grade_matches.py`'s pure CSV-merging
logic (not the video/FFmpeg parts, which need real footage and can only really be
checked by hand). Caught a real type-mismatch bug (see 3.2) before it ever reached
a real grading session.

**`tests/test_local_dev_mode.py`** — Tests that `backend/auth.py` and
`backend/jobs.py`'s local-mode fallback actually works: no token required,
create/read/update/list all functioning against an in-memory store. Uses small
fake stand-ins ("stubs") for the `fastapi`/`supabase` packages when they aren't
installed, so the *logic itself* can be verified even in an environment that
doesn't have every real dependency.

**`tests/test_showdown_import.py`** — Tests `showdown_import.py` against a
real, public Showdown replay (the actual battle log, copied verbatim from
that replay's own `.json` API response) — every roster, brought-4, lead,
winner, and timestamp assertion here is checkable against a real match, not
a synthetic guess. Also guards a real bug found while building it: resolving
`--player` against a username was done as `|player|` lines streamed in one
at a time, so naming the side whose username printed *second* in the log
locked onto the wrong default before that username had even been seen.

**`tests/test_frame_dedup.py`** — Tests `frame_dedup.py` against real generated
images (written with `cv2.imwrite`, not fakes), including the specific
behavior that matters most: comparing each frame against the last *kept*
frame rather than the last *seen* one, which is what correctly collapses a
long static screen down to a single kept frame while still catching slow
visual drift.

**`tests/test_compare_classifier_models.py`** — Tests the agreement-rate/
disagreement-collection logic in `compare_classifier_models.py` with a fake
classifier (real API calls need a live key), covering perfect agreement,
detected disagreements, and empty input.

**`tests/test_gemini_batch.py`** — Tests `gemini_batch.py`'s pure logic for
real (key encoding round-trips, request/result line building, markdown-fence
tolerance) with no mocking, and its orchestration functions
(`submit_battle_batch`/`wait_for_batch`/`collect_battle_batch_results`)
against a fake stub client that verifies the call sequence and arguments —
this proves the code *constructs* the calls Google's documented pattern
requires, not that Google's real batch endpoint accepts them (see the
module's own docstring for that honest caveat).

**`tests/README.md`** — Explains the two-tier philosophy in more depth: automated
tests for pure logic (this folder) vs. a human-assisted tool for anything that
genuinely requires watching real video (`grade_matches.py`).

### 3.7 Top-level config and infrastructure files

**`requirements.txt`** — Every Python package this project needs, one per line,
installed all at once with `pip install -r requirements.txt`.

**`.env.example`** / **`frontend/.env.example`** — Templates showing exactly which
secret values are needed (`GEMINI_API_KEY`, `SUPABASE_URL`, etc.) without
containing any real ones — copy to `.env` and fill in your own.

**`.gitignore`** — Tells version control (Git) which files to never track:
secrets (`.env`), huge generated files (videos, extracted frame folders),
installed dependencies (`node_modules/`), and Python's compiled-bytecode cache
(`__pycache__/`).

**`supabase_schema.sql`** — The one-time database setup script: creates the
`jobs` table with its columns, an auto-updating `updated_at` timestamp, and the
Row Level Security policies (Part 1.3) that let a user only ever see their own
rows.

**`schema.json`** / **`events.json`** / **`matches.csv`** / **`*.md` reports** —
Generated *output* files, not source code — the actual result of running the
pipeline once. Safe to delete and regenerate; not something you'd hand-edit.

**Other reference docs** — `ARCHITECTURE_HANDOFF.md` (the backend/system design
spec), `ADDING_A_NEW_GAME.md` (the adapter-system how-to), `METRICS_AND_DATAPOINTS.md`
(what each stat means and how it's computed), `PRODUCT_BRIEF.md`/`V1_SUMMARY.md`
(product vision and scope decisions, not code).

---

## Part 4 — How data actually flows

### 4.1 The pipeline, script to script (unchanged since the original POC)

```
VOD URL/file ──fetch_vod──────────────────▶ vod.mp4
adapters/ ──compose_schema─────────────────▶ schema.json   (the AI's instructions)
vod.mp4 ──structure_pass───────────────────▶ matches.csv   (when each match happens)
matches.csv + vod.mp4 ──analyze_matches────▶ events.json   (the structured truth)
events.json ──▶ battle_record / player_report / coach_report   (plain analytics)
events.json + PokeAPI ──meta_build─────────▶ meta/<format>.json   (knowledge base)
events.json + transcript + meta ──coach_chat──▶ answers to your questions
```

Everything hinges on **`events.json`** — a flat list of dicts describing every
event the AI observed. Extraction *produces* this file; every report, chart, and
the chat *only ever reads it* — nothing downstream re-touches the video. Understand
that one file's shape (documented in `ARCHITECTURE_HANDOFF.md` section 4) and you
understand the whole system's data model.

**There's a second, completely different way to produce that same
`events.json`:**

```
Showdown replay (.html/.json/URL) ──showdown_import.py──▶ events.json
```

`showdown_import.py` parses a Pokémon Showdown replay's own battle log
directly — no video, no Gemini, no AI guessing at all, since Showdown's log
is an exact record of the match. It writes the identical `events.json` shape
the video pipeline does, so every arrow after `events.json` in the diagram
above (analytics, meta_build, coach_chat, the dashboard) works completely
unchanged regardless of which of these two paths produced the data. This is
exactly the point of treating `events.json` as the one true interface
between "how did we learn what happened" and "what do we do with it."

This path is also reachable through the web app now, not just the command
line: `POST /jobs` with `source_type="showdown"` (uploaded replay files or
replay URLs, plus `player`) runs `backend/pipeline.py`'s
`run_showdown_pipeline()`, which calls this exact same `showdown_import.py`
under the hood, then the same three pure-analytics steps - every dashboard
tab works on a Showdown-sourced job with zero frontend changes, since
`GET /jobs/{id}/...` doesn't know or care which pipeline built that job's
`events.json`.

**The video pipeline's own `analyze_matches.py` step also has two modes now:**

```
matches.csv + vod.mp4 ──analyze_matches (live calls)───────▶ events.json   (default, instant per match)
matches.csv + vod.mp4 ──analyze_matches --use-batch-api────▶ batch_job_state.json ──(wait)──▶ events.json
```

`--use-batch-api` samples/de-duplicates frames and submits every match's
battle-event extraction as ONE Gemini Batch API job instead of many live
calls — half the token cost, same model, in exchange for the job finishing
on Google's schedule (target 24h, often quicker) rather than immediately.
Roster and winner reads still happen live either way (small, cheap, and the
batch prompts need the roster resolved first). The job's name and everything
needed to finish collecting it are saved to disk *before* the wait begins,
so `--resume-batch-job` can pick a job back up after a closed terminal —
either mode ends at the exact same `events.json` shape.

### 4.2 A browser loading the dashboard (the new, web-app part)

```
1. Browser opens http://.../dashboard/  →  gets the built React app (backend/static/)
2. React's App.jsx runs, and its first useEffect calls GET /auth/status
3. Backend checks auth.configured() — Supabase set up, or not?
      ├─ NOT configured  →  {"accounts_required": false}
      │      → frontend skips sign-in entirely, treats you as the built-in local user
      └─ configured       →  {"accounts_required": true}
             → frontend checks for an existing Supabase session
             → none found  →  shows the <Auth /> sign-in/sign-up screen
4. Once "ready" (local mode, or really signed in), App.jsx calls GET /jobs
5. Backend's list_jobs() asks: who is this? (Depends(auth.current_user))
      → looks at the Authorization header (or skips this check entirely in local mode)
6. jobs.py returns this user's jobs (from Postgres, or the in-memory local dict)
7. App.jsx picks a job (preferring one named "demo"), then calls 5 endpoints in
   parallel: record, report, matches/summary, opponent-strength, skill-scores
8. Each of those reads that job's events.json off disk and runs it through
   backend/analytics.py's compute_* functions
9. The JSON comes back to the browser, gets stored in React state, and the
   dashboard's tabs render it as cards, tables, and charts
```

### 4.3 Starting a brand-new analysis job

```
1. Frontend sends POST /jobs (a video URL or uploaded file, game, mode)
2. jobs.create_job() makes a new folder jobs/<random-id>/ and a job record
   (in Postgres, or the in-memory dict in local mode)
3. jobs.start_job() launches backend/pipeline.py's run_full_pipeline() on a
   background thread — the HTTP request returns immediately, it doesn't wait
4. pipeline.py runs fetch_vod → compose_schema → structure_pass → analyze_matches
   → battle_record → player_report → coach_report → transcribe, each as its own
   subprocess, inside that job's own folder
5. After each step, on_progress() updates the job's status/step in the store,
   so GET /jobs/{id} (polled by the frontend) reflects real progress
6. When it finishes, the job's status becomes "done" — from here on, it's
   readable through all the same endpoints as any other job
```

---

## Part 5 — How to explore this codebase yourself

**Reading a Python file:** start at the bottom. `if __name__ == "__main__":` is
where a script begins when you actually *run* it (as opposed to importing it from
somewhere else) — it usually parses `--flags` and calls `main()`. Read `main()`
top to bottom; it's the recipe, and every function defined above it is one
ingredient. The `"""triple-quoted text"""` right under almost every `def` in this
project explains that function's job in plain English — read that first, before
the code.

**Reading a React component:** look at the function's parameters first (its
props — what data does it need to be given). Then look for any `useState`/
`useEffect` calls near the top (what does it remember, what does it fetch). Then
read the `return (...)` at the bottom — that's the actual visual structure, and
`{ }` sections inside it are just JavaScript expressions being inserted.

**Running the automated tests yourself** (from `poc-starter/`):
```
py -m unittest discover -s tests -v
```
`-v` ("verbose") prints every individual test's name and result. A file full of
`ok`s at the end means every check passed; anything else names the exact test
(and its docstring, which explains what real bug it's guarding) that broke.

**Running one specific test file:**
```
py -m unittest tests.test_species_legality -v
```

**When you're stuck on a specific piece of code:** paste just that function (with
its docstring) into a new chat and ask "explain this line by line" — that's a
genuinely good way to learn, and it's exactly how this document itself was built:
one real function, one real bug, one real explanation at a time.
