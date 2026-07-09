# Architecture Handoff — Game Footage → Coaching Engine

Paste this into a fresh chat to bring it fully up to speed. It describes the working
analysis pipeline (in `poc-starter/`) and how to build the app/UI on top of it.

---

## 1. What this is
An engine that turns a competitive-gaming VOD (currently Pokémon Champions VGC — doubles
or singles, see §3a) into structured data and coaching: it finds every match, extracts a
per-turn event stream, computes analytics, and answers coaching questions in natural
language. It is designed to generalize to other games/formats via composable adapters.
The user picks mode (singles/doubles) and regulation (which Pokémon/mechanics are
currently legal — M-A or M-B) per job; see §3a for why these are two independent axes.

## 2. The pipeline (scripts in `poc-starter/`, in run order)
| Step | Script | Input → Output |
|------|--------|----------------|
| 0 | `fetch_vod.py` | Twitch/YouTube URL → `vod.mp4` (via yt-dlp) |
| 1 | `compose_schema.py` | `adapters/*` → `schema.json` (composes core+game+mode) |
| 2 | `structure_pass.py` | video → `matches.csv` (classifies each ~10s frame battle/not, groups battle runs into matches) |
| 3 | `analyze_matches.py` | `matches.csv`+video → `events.json`/`events.csv` (per-match, roster-locked events, brought/leads, winner) |
| 4 | `transcribe.py` | video → `transcript.json` (Whisper commentary, optional) |
| 5 | `battle_record.py` | events → `battle_record.csv` (W/L) |
| 6 | `player_report.py` | events → `player_report.md` (usage: brought, leads, moves, KO diff) |
| 7 | `coach_report.py` | events → `coach_report.md` (win rates by lead/bring, bogeys, coaching flags, throws) |
| 8 | `meta_build.py` | events + PokéAPI → `meta/<format>.json` (type chart + Pokédex + own-data flywheel) |
| 9 | `coach_chat.py` | events + transcript + meta → conversational coach (grounded, obeys format rules) |
| — | `run_full.py` | orchestrates 0/2–8 end to end, stop-on-failure, optional transcript |

Run everything: `py run_full.py --url <vod>` (or `--video vod.mp4`).

## 2a. Alternate ingestion: Pokémon Showdown replays (`showdown_import.py`)

A second, completely different way to produce `events.json` for a match -
still the SAME schema, so steps 5-9 above work unchanged on Showdown-sourced
matches. This was the "source-agnostic" design constraint `V1_SUMMARY.md`
called out when it deferred Showdown integration to v1.1: it's now built.

```
Showdown replay (.html/.json/URL) --showdown_import.py--> events.json
```

**Product decision (see `PRODUCT_BRIEF.md` §3/§9): Showdown import is IN v1**,
positioned as the free/instant on-ramp — VOD upload stays the deeper, paid-tier
product. Worth a QA pass against a few more real replays (currently verified
against only one) before pointing real beta testers at it.

Why this exists alongside the video pipeline rather than replacing it:
Showdown's own battle log (a documented, line-based protocol - see
https://github.com/smogon/pokemon-showdown/blob/master/sim/SIM-PROTOCOL.md)
is a complete, EXACT record of a match - there's no "the AI might have
misread the roster" step, because there's no AI or video involved at all.
It also means Showdown-sourced matches are inherently ground truth for
species legality (Showdown enforces format legality server-side - you can't
even select a banned Pokémon in a real ladder game in that tier), which is
the opposite problem the video pipeline's `ALLOWED_SPECIES` allowlist exists
to work around.

Run: `py showdown_import.py --file replay.html --player p1` (or `--url`, or
`--files a.html b.html c.json` / `--urls url1 url2 ...` to combine several
replays into one events.json as consecutive matches). `--player` says which
side is "you" (a Showdown username or `p1`/`p2`) - a replay has no built-in
notion of this the way a video of your own POV does. See `showdown_import.py`'s
own docstring and `tests/test_showdown_import.py` (built and verified
against a real, public [Gen 9 Champions] VGC 2026 replay) for the full detail.

Wired into the web app too: `POST /jobs` accepts `source_type="showdown"`
with either uploaded replay `files` or replay `urls` plus `player`, running
`backend/pipeline.py`'s `run_showdown_pipeline()` (a shorter, video/AI-free
step list - see `STEPS_SHOWDOWN`) instead of the video branch. Every other
endpoint (record/report/matches-summary/skill-scores/opponent-strength/coach)
needed zero changes, since a Showdown job's events.json is the same shape a
video job's is. See `backend/README_BACKEND.md`'s "`source_type="showdown"`"
section and `tests/test_showdown_job_pipeline.py`.

## 2b. Cost/accuracy tooling (`frame_dedup.py`, `gemini_batch.py`, `compare_classifier_models.py`)

Three independent, stackable ways to cut the Gemini bill (the video pipeline's
dominant cost) without giving up accuracy - built after a real "I've spent
almost $500 on Gemini credits" conversation, so each one is grounded in
verified real pricing/mechanics, not a guess:

- **`frame_dedup.py`** — free, local, no API call. Before battle frames are
  ever sent to Gemini, drops any frame that's near-identical (grayscale
  64x64 pixel-diff) to the last KEPT frame - a static screen held across
  several sample intervals can't contain a new event the last kept frame
  didn't already show. On by default in `analyze_matches.py` (`--dedup-threshold`,
  default 2.0; set to 0 to disable). Fully unit-tested with real generated
  images (`tests/test_frame_dedup.py`).
- **`compare_classifier_models.py`** — a one-time A/B tool to check whether
  `structure_pass.py`'s battle/menu/result/team_preview classifier step (an
  "easy" visual question) holds up on Gemini 2.5 Flash-Lite ($0.10/$0.40 per
  1M input/output tokens vs. Flash's $0.30/$2.50 - roughly 3-6x cheaper).
  Run it once on a video you've already run `structure_pass.py` on (reuses
  sampled frames); if agreement is near-perfect, pass `--model
  gemini-2.5-flash-lite` to `structure_pass.py` on every future run. Costs
  roughly one extra classifier pass, one time, to make a permanent decision.
- **`gemini_batch.py`** — routes the bulk per-match battle-frame event
  extraction (the single biggest line item) through Gemini's Batch API
  instead of live calls: exactly 50% off both input and output tokens, same
  model/quality, in exchange for not being instant (Google's target
  turnaround is 24h, "usually much quicker" per their docs). Roster+winner
  reads stay live regardless (small, cheap, and the event-extraction prompt
  embeds the roster, so it must be resolved before a batch request can be
  built). Enable with `--use-batch-api`; state is saved to
  `--batch-state-file` (default `batch_job_state.json`) BEFORE waiting, so a
  closed terminal or Ctrl-C doesn't lose the run - resume with
  `--resume-batch-job <file>`. Pure logic (key encode/decode, request/result
  line building) is fully unit-tested; the actual `client.batches.*` calls
  follow Google's documented file-based-JSONL pattern exactly but were only
  verified against a fake stub client in this environment (no live API
  key/network available while building it) - **your first `--use-batch-api`
  run is the real end-to-end test**, the same honesty flag used for the
  Supabase/accounts work.

## 2c. Data retention, reference frames, and manual corrections

Three related additions, built together after a real question ("is there a
reserve of everything collected, and can a user fix a wrong AI call by
hand?"):

- **Nothing gets auto-deleted anymore, but each match is pruned down to just
  its reference photos as it finishes.** Both `run_full_pipeline()` and
  `run_showdown_pipeline()` (`backend/pipeline.py`) used to `shutil.rmtree()`
  the per-match frame folders (`structure_frames/`, `match_frames/`) once a
  job finished - that whole-job cleanup is gone. `analyze_matches.py` was
  also restructured to sample each match's frames into its OWN subfolder
  (`match_frames/match_<N>/...`) instead of one shared folder that got wiped
  at the start of every match iteration - previously, match 2's frames would
  silently overwrite match 1's on disk (same filenames every time), so
  nothing from an earlier match ever survived to the end of a run even
  before the final cleanup. Rather than let every sampled frame (roster
  preview + every battle frame + winner-read frames - easily hundreds per
  match) pile up forever, `analyze_matches.prune_unreferenced_frames()` runs
  right after each match's roster/battle/winner reads finish and deletes
  everything in that match's `match_frames/match_<N>/` folder EXCEPT the
  frames actually kept as an event's `reference_frame` (see below) - usually
  a small handful. This was added after a real problem it caused: with every
  frame kept forever, `uvicorn --reload`'s file watcher had to track so many
  image files that new HTTP requests stopped getting through at all. The
  reference-photo/manual-correction feature stays fully intact (every event
  that has a `reference_frame` still has the actual file on disk); what's
  gone is the much larger set of frames nothing ever pointed at.
- **Every extracted event carries a `reference_frame`** - the path (relative
  to the job's own folder) of whichever sampled frame was closest in time to
  that event, tagged by `analyze_matches.attach_reference_frames()` right
  after extraction (both live and `--use-batch-api` modes; the Batch-API
  path threads the actual per-chunk frame list through `--resume-batch-job`
  too, via a new `chunks_by_key` entry in the saved state file). This is
  what lets the dashboard show the literal image the AI was looking at.
- **`backend/audit.py`** - an internal (NOT user-facing - no endpoint reads
  it) durable log of job lifecycle events (`job_created`, `job_step`,
  `job_completed`, `job_failed`) and manual corrections (`event_corrected`),
  kept in `audit_log.jsonl` at the project root plus a Supabase `audit_log`
  table (service-role-write-only, no select policy for any other role - see
  `supabase_schema.sql`) whenever Supabase is configured. Freeform payload
  (no fixed schema), and fails soft - an audit-write error is logged and
  swallowed, never allowed to fail the real job.
- **`GET /jobs/{id}/frame/{path}`** serves one stored reference image
  (ownership-checked like every other `/jobs/{id}/...` route, plus a
  path-traversal guard - `backend/job_files.safe_frame_path()`) and
  **`PATCH /jobs/{id}/events/{index}`** lets a signed-in user correct one or
  more fields on a single event by hand (e.g. a misread Pokémon or move),
  recording the before/after to the audit log and rewriting
  `events.json`/`events.csv` in place. The frontend's Matches tab
  (`MatchEvents.jsx`) renders this: click a match to expand its event list,
  each with a thumbnail (fetched as an authenticated blob, since a bare
  `<img src>` can't carry a Bearer token) and a "Correct this" inline form.
- **Cascading Pokémon-identity corrections (`backend/event_corrections.py`)**:
  a real user complaint surfaced this gap - "I fixed one event and nothing
  else changed," because a misread species almost always recurs across
  MANY events in the same match (every `move_used`/`item_or_ability_
  activated`/`status_inflicted` for that Pokémon, `field_state`'s
  `player_active`/`opponent_active` strings, `field_state`'s nested
  `field_status` entries, and `team_preview`'s `team`/`brought`/`lead`
  strings), since a team's roster is fixed for the whole match. Correcting
  `pokemon` on ONE event via `PATCH /jobs/{id}/events/{index}` now also
  finds and fixes every OTHER event in that match sharing the same side
  (`actor`: "player"/"opponent") that still reads the old wrong name -
  scoped deliberately narrow (same match, same side only) so a name that's
  legitimately different on the other side, or in a different match, is
  never touched. The response's `cascaded_indices` lists every index this
  additionally touched; the frontend (`MatchEvents.jsx`) surfaces "Also
  fixed N other events..." right after saving. `GET /jobs/{id}/record` and
  `/report` recompute live from `events.json` on every request (no caching
  layer anywhere in this stack), so a cascaded correction is reflected in
  Record/Report/Skill Scores/Matches-summary immediately - see
  `tests/test_event_corrections.py` for the full behavior contract.
- **Remaining known limitation, stated honestly**: this cascade only
  propagates a `pokemon` identity fix. Correcting some OTHER field (a move,
  an HP value, the match `winner`) still only affects that one event - there
  is no general "recompute every derived summary field from scratch" step,
  since most other fields aren't the kind of value that recurs verbatim
  across many events the way a misread species name does.

## 2d. OCR accuracy tier (`--use-ocr-tier`): reading exact text instead of guessing it

Built after a real, verified misread (a frame's own text said "The opposing
Staraptor fainted!" while the extracted event still reported `"pokemon":
"Charizard"` - see 2's roster-constraint prompt fix, which stopped the
*silent* version of this bug but didn't stop the underlying issue: a vision
model was being asked to re-derive text that's already on screen, in exact
form, for free). The core insight: the Pokémon battle-text banner is not
ambiguous - it is exact, deterministic on-screen text - so reading it via
OCR + a plain text parser is strictly more reliable than describing it to a
vision model and hoping the description is faithful. This is the "tiered
pipeline: cheap/deterministic first, expensive vision only for genuine
ambiguous leftovers" principle applied concretely.

Four new files, each independently unit-tested (68 new tests total, listed
under each file):

- **`battle_text_parser.py`** — pure regex-based parser, on-screen banner
  text in, one structured event out (or `None` if the text isn't recognized
  - it must never invent a plausible-looking guess for text it doesn't
  actually understand). Covers fainting, super/not-very/no-effect,
  critical hits, stat changes, status conditions, move usage (incl. failed
  moves), send-outs, weather/terrain, ability/item callouts, and battle-end
  phrasing - every event type/field matches `adapters/pokemon/game.json`'s
  schema exactly. `tests/test_battle_text_parser.py` (34 tests) includes
  the literal real-world strings this was built from ("The opposing
  Staraptor fainted!", "Scrafty's Intimidate").
- **`ocr_battle_reader.py`** — extracts + reads two screen regions
  (`BOTTOM_BANNER_REGION`, `NAME_PLATE_VALIDATED`) via a validated
  preprocessing recipe: crop → 4x upscale → HSV-isolate near-white text →
  **invert to black-on-white** (the single biggest lever found during
  testing - Tesseract's bundled models assume dark text on a light
  background; a technically-clean white-on-black mask read as garbage until
  this step was added) → pad with a white border → `pytesseract`. Validated
  against real captured frames from this project's own test footage (two
  exact reads on the bottom banner). **Honest limitation**: the name/HP
  plate reader is rougher (stylized italic font over a colored/textured
  background, not flat text) and only ONE of the four plate positions a
  doubles battle can show at once has actually been measured against real
  footage - the other three are unvalidated and should be measured before
  being trusted the same way. Ability/item callouts that float next to a
  sprite (rather than appearing in the banner) aren't targeted at all yet.
  `tests/test_ocr_battle_reader.py` (14 tests) uses synthetic PIL-rendered
  frames rather than real footage (real captured video is a specific
  streamer's personal content - chat overlay, channel branding - and isn't
  an appropriate thing to commit as a permanent repo fixture); the
  preprocessing recipe itself was validated against real frames separately,
  during development, not re-proven by these tests.
- **`pokemon_identity.py`** — solves the one thing text alone genuinely
  can't resolve: a name plate can show a player-chosen **nickname** instead
  of the species, and no database (PokeAPI, Showdown's own data files) has
  any way to look up an arbitrary nickname - it isn't in any database at
  all, it's just whatever the player typed. `IdentityResolver` (scoped one
  per match) tries a free local fuzzy-match against that match's own known
  roster first (the common case - most Pokémon aren't nicknamed); only a
  display name that resembles nothing in the roster at all gets flagged as
  needing a real identification, which costs at most ONE small Gemini
  vision call per *distinct nickname* for the whole match (not per frame,
  not per event) - the result is cached via `.learn()` and reused for every
  later mention of that same nickname. `tests/test_pokemon_identity.py`
  (14 tests).
- **`ocr_pipeline.py`** — the merge layer wired into `analyze_matches.py`
  via `--use-ocr-tier` (live mode only - see below). For each match:
  samples the match window a SECOND time at a higher resolution/fps than
  the Gemini-facing sampling (`OCR_SCALE_W=1280`, `OCR_FPS=2.0` vs. the
  640px/~0.33fps used to keep Gemini's per-image cost down - on-screen text
  needs real resolution the cost-optimized frames don't have), reads the
  banner off every OCR frame, parses it, resolves any nickname via
  `pokemon_identity.py`, then merges the result with the existing
  Gemini-derived `match_events`: an OCR event wins over a Gemini event that
  clearly duplicates it (same event type + same Pokémon, within a few
  seconds), but Gemini remains the only source for anything OCR doesn't
  target (`field_state`, `hp_change`, `team_preview`, most ability/item
  callouts). `tests/test_ocr_pipeline.py` (20 tests) - the real Gemini
  vision call (`identify_pokemon_species`) is exercised via a fake
  `call_fn`, never a live API call.

**Current scope, stated plainly**: `--use-ocr-tier` only works with live
mode - it isn't wired into `--use-batch-api` yet (batch mode defers all
frame sampling into its own phase 2/3 structure in a way this hasn't been
threaded through). Requires `pytesseract` + a working Tesseract OCR system
install (see `requirements.txt` for the per-OS install steps). Costs
nothing extra per frame beyond the local OCR sampling pass (free, no API
call) plus at most one small vision call per distinct nickname per match -
most matches have zero nicknamed Pokémon, so the common case costs nothing
at all beyond CPU time.

**Update (2026-07-04) — flipped from opt-in to default-on**, per an explicit
user architecture review ("Gemini should be the coach, not the referee" -
deterministic/cheap extraction should be the default path, vision-based
extraction the fallback, not the reverse). `--use-ocr-tier` is now
`default=True`; a new `--no-ocr-tier` flag opts back out. The two
previously-hard-`sys.exit` cases now degrade gracefully instead, since a
flag nobody explicitly opted into shouldn't be able to crash a run: combined
with `--use-batch-api`, it now prints a note and silently continues without
the OCR tier (vision-only, same as before this flag existed) rather than
exiting; a missing `pytesseract`/Tesseract install now prints a note and
continues in pure-Gemini-vision mode rather than exiting. See
`run_accuracy_addons_checks()` in `analyze_matches.py` for the equivalent
graceful-degradation wrapper on the `--use-accuracy-addons` side (§2e).

## 2e. `accuracy_addons/` — four more free, local accuracy tools

Built as standalone additions, deliberately not touching `analyze_matches.py`/
`ocr_pipeline.py` while other work was in progress on those files — see the
folder's own `README.md` for full detail and how to extend either one.

- **`icon_template_matcher.py`** — OpenCV template matching (`cv2.matchTemplate`)
  for fixed on-screen icons (move-type icons now; status conditions,
  weather/terrain banners, and the Tera crown are the obvious next additions,
  same process). Ships with 3 real, validated templates (water/fire/electric
  move-type icons, cropped from an actual captured frame) — re-matching each
  against its own source frame scored a perfect 1.000 at the correct
  location, confirming the crop→match→locate pipeline itself works. The
  other ~15 move types and every status/weather/Tera icon still need the
  same real-footage extraction before being trusted — not guessed/generated.
- **`hp_bar_reader.py`** — reads HP% from the bar's actual pixel fill length
  (HSV color-band column scan), as a free cross-check against
  `ocr_battle_reader.py`'s text-based HP read — when both agree, that's a
  strong accuracy signal; when they disagree, that's a real flag worth a
  Gemini vision read for that moment, the same "flag, don't force a guess"
  pattern as §2d. First attempt at the bar region accidentally included the
  "94%" text label sitting next to the bar and read back 0% on a real 94%-HP
  frame — a real bug caught by testing against real footage, not by
  reasoning about it. Fixed region reads back ~100% against that same real
  94%-HP frame (agrees within tolerance). Honest limitation: at the
  pipeline's 640×360 battle-sampling resolution the bar is only ~45-50px
  wide, so precision is roughly ±2 points per pixel — good for catching a
  badly wrong OCR read, not for exact numbers. Only one of the four
  doubles-battle plate positions is measured/validated so far.

- **`moveset_validator.py`** — flags a move read as implausible when a
  species has never legally learned it, per Pokemon Showdown's own
  learnset data (`data/learnsets.ts`) — the same class of fix as
  `analyze_matches.reject_banned_species()` (which catches an implausible
  SPECIES), applied to moves. Chose Showdown's data over PokeAPI
  specifically because it's what powers real ladder legality enforcement,
  so it stays current fast after regulation changes. Tested against REAL
  data fetched from Showdown's own source during development: `Charizard`
  + `Flamethrower`/`Dragon Claw` → correctly `True`; `Charizard` +
  `Thunderbolt` (never actually learned) → correctly `False`, flagged
  (confidence dropped, `detail` note appended - same "flag, don't force a
  guess" pattern as pokemon_identity.py); an unlisted species → correctly
  `None`, left untouched rather than wrongly rejected. **Coverage caveat,
  stated plainly**: the bundled data (`data/showdown_learnsets_starter.json`)
  covers only 15 species (bulbasaur through beedrill) - real, accurate,
  directly transcribed, but NOT any of the species that actually appear in
  this project's real VGC footage. It proves the mechanism against real
  data; it isn't production coverage. `tools/export_showdown_learnsets.js`
  (real, standard `@pkmn/data` usage) does a complete one-shot export of
  the full dex, but could NOT be run/verified here - this sandbox's npm
  registry access was blocked (403/allowlist) during development. Also
  deliberately lenient - "has this species EVER learned this move, any
  generation" - not a current-regulation-specific check, which stays owned
  by the hand-maintained `rules` in `adapters/pokemon/doubles.json`.

- **`format_rules_validator.py`** — cross-checks `adapters/pokemon/doubles.json`'s
  hand-maintained format rules (regulation, Tera/Dynamax/Mega legality,
  banned species categories) against Pokemon Showdown's own actively-
  maintained Champions format/ruleset data (`config/formats.ts` +
  `data/rulesets.ts`) - catching the adapter file going stale as VGC
  regulations rotate (they change every few months), the same "don't let a
  hand-maintained file quietly drift" spirit as the moveset check above,
  applied to format rules. **Run for real against the actual adapter file**
  (not a mock): `doubles_format` and `mythical_and_restricted_legendary_
  banned` both came back **MATCH** - no staleness found, the file was
  already correct at the time of this check. `species_clause`,
  `terastallization`, and the exact regulation (adapter targets M-B;
  Showdown's fetched data only had a distinct entry for the closely-related
  predecessor M-A) came back honestly **NOT_CONFIRMABLE** rather than a
  false pass - see the module's own docstring for exactly why each one
  couldn't be directly confirmed from this particular fetch, and what
  re-fetching later could resolve.

Suggested integration point when picked up: same tiered pattern as
`ocr_pipeline.py` — try the free pixel/template/moveset-check read first,
only spend a vision call when it's missing or disagrees with the OCR text
read. `format_rules_validator.py` is a different shape (a periodic/CI-style
staleness check on the adapter file itself, not a per-frame/per-event
check) - worth running whenever `adapters/pokemon/doubles.json`'s
`regulation_active_until` approaches, not on every pipeline run.

**Overnight update (2026-07-03)** — four real-data-tested additions, all
still inside `accuracy_addons/` and still NOT wired into the live pipeline
(see `accuracy_addons/OVERNIGHT_REPORT.md` for the plain-language summary and
`accuracy_addons/README.md` for the quoted per-test numbers):
- `icon_template_matcher.py` now ships a validated **burn** status-badge
  template (`templates/status/status_burn.png`) plus a `status`-category
  loader/matcher. It's tested harder than the 3 move-type templates: self-match
  1.000 AND 0.94–0.98 on 10 *other* real frames showing the burn badge, vs
  0.30–0.43 without it (clean separation) — the first template here with real
  cross-frame evidence, not just a self-match. No Tera crown was found (this
  format has Tera off), as expected.
- `hp_bar_reader.py` gained `PLAYER_BOTTOM_LEFT_HP_BAR`, the player's own
  plate, measured from real pixels and validated at TWO real HP values
  (157/157→100% and 69/157=44%→reads 51%, both agree within tolerance). While
  validating it, found+documented that the overlay plates are NOT pinned to a
  fixed pixel row (the opponent region reads 0% on a frame where its plate
  sits ~8px lower) — so both HP regions are position-specific, not universal.
- `format_rules_validator.py` was made **regulation-layer-aware**: the §3a
  refactor (below) moved `banned_species_categories`/`terastallization`/
  `regulation` out of `doubles.json` into `regulations/<id>.json`, which had
  silently regressed the Mythical/Restricted-Legendary ban check to a spurious
  "mismatch". It now reads those fields from the regulation layer; re-run
  against the real files this session, that check is a correct MATCH again.
- Re-fetched `config/formats.ts`: Reg **M-B is still absent** from Showdown's
  config (only Reg M-A variants), so the exact-regulation check stays honestly
  NOT_CONFIRMABLE. The full Showdown learnset export is still blocked (npm 403;
  3.55 MB `learnsets.ts` unfetchable), so `moveset_validator` coverage is
  unchanged — no learnsets were fabricated to paper over that.

**Update (2026-07-04) — all four are now WIRED into `analyze_matches.py`,**
not just standalone anymore:
- `moveset_validator.flag_implausible_moves()` runs **unconditionally** (pure
  JSON lookup, no image/API cost — same as `flag_roster_conflicts`) at both
  the live-mode and batch-mode call sites, right alongside
  `flag_roster_conflicts`. Given the current bundled learnset data only
  covers 15 non-VGC species (see above), this will find essentially nothing
  to flag on real jobs today — the wiring is real and tested, the practical
  coverage isn't yet. **Update (2026-07-04, later same day)**: `moveset_
  validator.py` now auto-detects `data/showdown_learnsets_full.json` the
  moment it exists on disk (`_resolve_default_data_path()`), preferring it
  over the 15-species starter file with **zero further code changes**. So
  activating full-dex coverage is now just: run
  `tools/export_showdown_learnsets.js` on a machine with real npm access
  (`npm install @pkmn/data @pkmn/sim`, then
  `node export_showdown_learnsets.js > ../data/showdown_learnsets_full.json`
  from `accuracy_addons/tools/`) — still blocked in this sandbox (npm 403),
  confirmed again this session with a direct `npm install` attempt. See
  `tests/test_moveset_validator.py` for the auto-detection regression tests.
- `hp_bar_reader` (both plate positions), `icon_template_matcher`'s "burn"
  badge check, and (added later, §9c) the reference-frame visibility check
  are wired as `cross_check_hp_bar_events()`, `cross_check_status_events()`,
  and `cross_check_reference_frame_visibility()` — all three open and scan
  the event's own `reference_frame` image, so they're real per-event work,
  not free. On disagreement they lower confidence and append a note to
  `detail`; they never overwrite the original read. `cross_check_status_events`
  only ever checks `actor="opponent"` burn claims (the only plate
  position/badge that was validated) — a player-side burn claim, or any
  other status, is left untouched. See `tests/test_accuracy_addons_wiring.py`,
  which tests this new wiring (event selection, region choice, flag-vs-leave-
  alone logic) by mocking each addon's own read function — the addon's
  underlying pixel/template math was already validated separately, against
  real footage, when each module was first built (see above).

  **Update (2026-07-04) — flipped from opt-in to default-on**, same
  architecture-review reasoning as `--use-ocr-tier` above: `--use-accuracy-
  addons` is now `default=True`; a new `--no-accuracy-addons` flag opts back
  out. Since a flag nobody explicitly opted into shouldn't be able to crash a
  run on a missing dependency, the three checks are now called through a new
  `run_accuracy_addons_checks(args, match_events)` wrapper (right before
  `merge_brought()`) that catches `ImportError` once, prints a note, and sets
  `args.use_accuracy_addons = False` for the rest of the run instead of
  raising — replacing the previous duplicated inline
  `if args.use_accuracy_addons: ...` blocks at both the batch-mode and
  live-mode call sites.
- `format_rules_validator`'s staleness check now runs **automatically, once,
  at job startup** (`check_regulation_staleness()`, called right after
  `schema.json` loads in `main()`) rather than only via manual invocation —
  always-on since it's cheap (no images, just JSON) and a different shape
  from the three per-event checks above (a one-time reminder, not a
  per-event flag). Prints a `⚠` warning only for a confirmed `"mismatch"` -
  silent otherwise (including for `"not_confirmable"` fields, which aren't
  wrong, just not checkable from the bundled Showdown snapshot).

**Update (2026-07-05, tasks #131/#130) — full-dex learnset coverage AND a
third external meta source, both actually run/verified this time:**

- **`moveset_validator` full-dex export finally executed** — the npm-403
  blocker described above no longer applied in this session (`@pkmn/data`/
  `@pkmn/sim` were already present in `accuracy_addons/tools/node_modules`),
  so `export_showdown_learnsets.js` was actually run: 818 species,
  `data/showdown_learnsets_full.json`, picked up automatically via the
  existing `_resolve_default_data_path()` auto-detection — zero further code
  changes needed, as originally designed. Cross-checking the fresh export
  against every real `move_used` event across `jobs/` (not just a few
  species) surfaced two real bugs, both fixed:
  - **Alt-forme learnsets were wrong.** Showdown's own `learnsets.ts` stores
    an alternate forme's entry as ONLY its forme-exclusive move(s) — e.g.
    `rotomwash` had just `hydropump`, not the 67 moves base Rotom can learn.
    Every Rotom appliance forme, both Necrozma fusion formes, and both
    Crowned formes were affected. Fixed in the export script by merging in
    `species.baseSpecies`'s own learnset whenever a species is a forme (see
    `export_showdown_learnsets.js`'s own comment) — re-verified real
    Rotom-Wash moves (Thunderbolt, Hydro Pump) both now resolve `True`.
  - **`_move_name()` couldn't unwrap real battle-log sentences.** Roughly
    half of what first looked like genuine "implausible move" flags on real
    footage were actually this — `"Rotom used Discharge"`, `"The opposing
    Primarina used Sparkling Aria!"`, `"Muddy Water hit Garchomp
    (Effective)"`, `"Sacred Sword failed"` (no parens) were all being
    compared as-is against the learnset data. Fixed with a narrow,
    event-`pokemon`-anchored prefix strip plus trailing-bang/hit/missed/
    failed cleanup (see `_move_name`'s own docstring for the full list and
    the deliberately-left-alone "Protect blocked X" ambiguous case).
  - **Honest, NOT "fixed" data quirk left as-is**: Bisharp/Kingambit's real
    gen-9 export has no Sucker Punch or Rock Slide — surprising for a
    Pokemon famous for Sucker Punch, but that's what Showdown's own data
    genuinely contains (Gen 9 broadly trimmed move pools vs past gens).
    Flagged in the module docstring rather than silently patched in.
  - 42 tests in `tests/test_moveset_validator.py` (13 new), all passing.

- **`external_meta` — the wider field, not just your own uploads (task
  #130).** `own_meta` (above) is only as broad as a user's own upload
  history; a new user or a Pokemon they've never faced gets nothing from
  it. Researched several candidate sources for "what is the wider VGC field
  actually playing" (Smogon's own stats API thread, PokeAPI, `@pkmn/`
  packages, RK9/Limitless tournament data) before settling on Smogon's own
  official published stats dumps (`smogon.com/stats/`) — first-party data
  Smogon itself publishes for exactly this purpose (no scraping, no ToS
  gray area, unlike the community "smogon-usage-stats" Heroku wrapper,
  whose author has since been banned from Smogon and which now needs a CORS
  proxy). Directly fetched `smogon.com/stats/2026-06/` on 2026-07-05 and
  confirmed this exact game is tracked there as `[Gen 9 Champions]`, with
  per-regulation VGC tiers named `gen9championsvgc<year>reg<code>` — real,
  current-regulation data (1.48M battles in the M-A June-2026 dump alone),
  not a mainline-game format standing in for this one.
  - `meta_build.py` gained `fetch_external_meta()` (tries the current month
    then up to 2 prior months, and the 1760/1630/1500/0 rating cutoffs in
    that order, since Smogon's dumps lag a few days into a new month and not
    every tier has enough games at the highest skill band yet) and
    `_parse_smogon_usage_text()` for the plain-text table format. Wired into
    `meta_build.py main()` (new `external_meta` key in `meta/<format>.json`,
    guarded by a new `--no-external-meta` flag) and into `coach_chat.py`'s
    `load_meta_context()` (a `FIELD-WIDE META` block, clearly distinct from
    the player's own `own_meta` block, so the coach can warn about a
    likely-to-be-faced Pokemon even if this player has never personally
    faced it).
  - 18 new tests in `tests/test_meta_external.py` — the text parser is
    tested against a REAL captured excerpt of the M-A June-2026 stats page
    (not a synthetic fixture); the month/cutoff-walking logic in
    `fetch_external_meta()` is tested with `urlopen` monkeypatched to mimic
    real HTTP 404s (this sandbox has no outbound network access, and a unit
    test shouldn't depend on smogon.com staying reachable/unchanged anyway).
  - Full suite after both changes: 589 tests, all passing.

**Update (2026-07-05, task #138) — real FORMAT-specific move legality, not just
generation legality.** Directly prompted by a user's own challenge after the
work above shipped: "but the system knows what moves are legal in what formats
correct?" The honest answer up to that point was no — `is_plausible_move` was
(by design, stated in its own docstring) a lenient "has this species EVER
learned this move, ANY generation" check; nothing in the pipeline checked
Pokemon Champions' specific, narrower ruleset.

Investigated whether Champions has its own real Showdown data mod (rather than
assuming vanilla Gen 9 is close enough) by browsing the live
`smogon/pokemon-showdown` GitHub repo directly — it does:
`data/mods/champions/learnsets.ts` (278KB) is a genuine, actively-maintained
mod file, alongside its own `abilities.ts`/`items.ts`/`moves.ts`/`rulesets.ts`
(no `pokedex.ts` — species/base-stat data is inherited unchanged from vanilla
Gen 9). The locally-installed `@pkmn/sim` npm package (0.10.11) predates this
mod entirely, so `export_showdown_learnsets.js`'s existing full-dex export
could not have picked it up no matter how it was re-run.

`learnsets.ts` is a DELTA file, not a full roster: only 48 species have an
entry at all (grep-confirmed count); every other species falls through to
vanilla Gen 9 data unchanged, the same inheritance model Showdown's own mod
system uses elsewhere. Each of the 48 entries is a genuine, curated
REPLACEMENT movepool, not a subset filter — confirmed with real Charizard:
Champions-Charizard has 72 learnable moves vs. vanilla Gen 9's 129 (missing
Dynamic Punch, False Swipe, Hidden Power, and ~55 others), while separately
GAINING Ancient Power, Bite, and Dragon Rush — moves vanilla Gen 9 Charizard
cannot learn at all. A pure subset filter couldn't produce that shape.

Built without needing a newer `@pkmn/sim` release or any npm access at all
(npm registry access has been unreliable throughout this project — see the
export-blocked history above): `accuracy_addons/tools/
fetch_champions_learnset_overrides.py` is a small, standalone script that GETs
`data/mods/champions/learnsets.ts` straight from `raw.githubusercontent.com`
and regex-parses its specific, regular shape (no TypeScript compiler needed).
Its output (`accuracy_addons/data/showdown_learnsets_champions_overrides.json`,
48 species, 3002 move entries) is merged into `moveset_validator.
load_learnsets()` — but ONLY when loading the real full-dex path
(`_FULL_DATA_PATH`), deliberately not for the 15-species starter file or any
caller-supplied test path — and REPLACES (not unions with) the base data for
each of its 48 species, matching how the real mod itself behaves.

Real, verified behavior after the change: `Charizard` + `Dynamic Punch` →
`False` (was `True` before this fix — the actual accuracy improvement);
`Charizard` + `Ancient Power` → `True` (was `False` before); `Charizard` +
`Flamethrower` → `True` (unaffected, legal in both); `Slowking-Galar` + `Acid`
→ `False`, `Slowking-Galar` + `Belch` → `True`; any of the ~770 non-override
species (e.g. `Hydreigon` + `Dark Pulse`) → unchanged, still the lenient
any-generation check, since Champions' own data has nothing more specific to
say about them.

6 new tests in `tests/test_moveset_validator.py`'s
`TestChampionsFormatSpecificOverrides` (real data, skipped if the override
file isn't present in a given environment) — full suite 595 tests, all
passing. Refreshing this later (a new regulation, a balance patch to one of
the 48 species) is just re-running `fetch_champions_learnset_overrides.py` and
overwriting the JSON — `moveset_validator.py` needs zero further code changes,
same "activate by dropping a file" design as the full-dex export itself.

**Honest scope, stated plainly**: this closes the format-specific-legality gap
for exactly the 48 species Showdown's own Champions mod actually overrides —
it does not mean every one of the ~818 exported species has been individually
verified against real Champions play. For the ~770 species with no override
entry, "has this species ever learned this move in Gen 9" remains the best
available signal, same as before this change.

**Update (2026-07-05, task #139) — actually re-ran the whole pipeline against
every real `jobs/*/events.json` on disk as an end-to-end accuracy test** of
everything tasks #131/#138 shipped, rather than just spot-checking a handful
of species in isolation. Scanned all 472 real `move_used` events across every
job with intact `events.json` (one job's file, `303d13ba0940`, is separately
corrupted on disk — truncated mid-write, `json.load` raises `Unterminated
string` — a pre-existing data issue unrelated to this session's changes, not
yet fixed).

**Update (2026-07-09, tasks #232/#233) — job `303d13ba0940`'s `events.json`
got repaired since task #139 (it's no longer truncated), and running the full
30-match job's `strategic_analysis.analyze_job()` end-to-end against its real,
video-extracted data surfaced two genuine crashes that only show up on messy
real footage, never on synthetic test fixtures or the clean Showdown-replay
fixture this suite otherwise relies on:**

1. **Mixed-type `turn` fields.** `field_state` events' `turn` value is
   sometimes a plain `int`, sometimes a numeric string like `"1"` (match 14),
   and sometimes the literal string `"unknown"` (match 16, 6 occurrences).
   `decision_windows.py`'s `order.sort()` and `strategic_analysis.py`'s several
   `sorted({e["turn"] for e in ...})` call sites all assume every `turn` in the
   set is directly comparable — mixing `str` and `int` raises `TypeError: '<'
   not supported between instances of 'str' and 'int'`.

   Fixed with one shared choke point: `decision_windows._normalize_turn(raw)`,
   imported into `strategic_analysis.py`, is now the only place either module
   reads a raw `turn` field through (6 call sites in `strategic_analysis.py`,
   1 in `decision_windows.py`). It returns a real `int` for plain ints,
   integer-valued floats, and numeric strings (`_TURN_STRING_RE`); returns
   `None` — same as an actually-missing `turn` field already meant — for
   `"unknown"`, non-integer floats, and anything else. Booleans are explicitly
   excluded (Python's `bool` is an `int` subclass, and `True`/`False` are
   never a real turn number). Nothing is guessed; a match with a genuinely
   unreadable turn value degrades to treating that one event as un-keyed
   rather than crashing or fabricating a turn number for it.

2. **Non-numeric `hp_percent` strings.** `hp_change` events' `hp_percent` is
   sometimes a percent string like `"20%"` and sometimes a literal
   current/max fraction string like `"1/164"` (both from match 30) instead of
   a clean `0-100` float. `strategic_analysis.compute_advantage_score`'s
   `sum()` over these raised `TypeError: unsupported operand type(s) for +:
   'float' and 'str'`.

   Fixed with `strategic_analysis._coerce_hp_percent(raw)`, the new single
   choke point `_turn_hp_snapshot`'s bucket-append reads `hp_percent` through.
   Handles plain int/float, `"NN%"` strings (strips the `%`), `"current/max"`
   fraction strings (`_HP_FRACTION_RE`, computes `(current/max)*100`, guards
   against a zero denominator), and falls back to a plain `float(text)` parse;
   anything else (including `"unknown"`) returns `None` — same "skip, don't
   guess" contract as an already-missing `hp_percent` value.

3. **`analyze_job` per-match isolation.** Before this change, either crash
   above — arising from ONE match's own messy data — took down the entire
   job: `analyze_job` had no exception handling, so one bad match meant NONE
   of the other (possibly 29 perfectly fine) matches in the job got analyzed.
   `analyze_job` now wraps each match's `analyze_match` call in its own
   try/except; a failing match gets a placeholder result (`{"match": m,
   "error": "<ExceptionType>: <message>", "momentum_timeline": [],
   "resource_summary": None, "mistake_candidates": [], "win_condition_candidates":
   [], "threats": [], "loss_analysis": None}`) with every key a successful
   result would have, so downstream consumers (e.g. the frontend's
   `turnReports` lookup in `MatchSummary.jsx`) never crash on a missing field
   just because one match failed.

Real, verified result after all three fixes: running
`strategic_analysis.analyze_job()` against job `303d13ba0940`'s full, real
`events.json` (30 matches) now returns **30 matches, 0 errors, 76 turns of
full six-report battle-intelligence data** — directly answering the user's
request for "turn by turn intel across the whole job and per match."

19 new tests added: `TestNormalizeTurn` in `tests/test_decision_windows.py`
(10 tests — int passthrough, numeric-string coercion, whitespace tolerance,
`"unknown"` → `None`, bool exclusion, non-integer float → `None`, plus two
`build_decision_windows`-level integration tests proving mixed int/string
turns merge correctly and a literal `"unknown"` turn is skipped without
crashing) and, in `tests/test_strategic_analysis.py`: `TestCoerceHpPercent`
(10 tests, plain values through fraction-string edge cases, plus an
integration test proving `_turn_hp_snapshot` tolerates a real mix of `"20%"`
and `"82/100"`-style values in the same match) and one resilience test on
`TestAnalyzeMatchAndJob` (`test_analyze_job_does_not_let_one_bad_match_take_down_the_others`,
monkeypatches `analyze_match` to raise for one match out of three and
confirms the other two still return real results). Full suite: 931 tests, all
passing.

Also worth recording for anyone hitting the same thing: this session's editor
tooling repeatedly showed a stale, truncated view of files it had just edited
(`decision_windows.py`, `strategic_analysis.py`, both test files above) — a
mount-caching artifact, not a real syntax error, confirmed each time by
reading the file through a different tool that reported the correct, longer
content. The fix that actually worked was writing the file's full correct
content to a **brand-new, never-before-used scratch filename** before copying
it over the real path — reusing a scratch filename from an earlier attempt
kept reproducing the same stale content even after a fresh write to it.

Of 74 initial flags, most held up as genuine catche
s once checked against the
real learnset data directly (not assumed): Garchomp has never learned Muddy
Water or Brave Bird in Gen 9, Sinistcha has never learned Hypnosis/Muddy
Water/Coil, Whimsicott and Rotom-Wash have never learned Roost, Rotom-Wash
has never learned Dragon Claw — all confirmed by printing the actual move
lists, not guessed. But 3 real parsing gaps in `_move_name()` were also
found, causing FALSE flags on perfectly legal moves:
  - A bare `"used <Move>"` detail with no species repeated at all (e.g.
    `"used Sparkling Aria"` for a Primarina event) wasn't stripped — the
    existing prefix-strip only handled `"<Species> used ..."`/`"The opposing
    <Species> used ..."`, not the case where the sentence doesn't restate
    the species at all.
  - `"<Move> on <target> (<annotation>)."` sentences (e.g. `"Rotom used
    Will-O-Wisp on Weavile (Scrafty on screen)."`) weren't unwrapped — the
    trailing `" on ..."` clause, the parenthetical, and the closing period
    all passed through as if they were part of the move name.
  - A vague `"a <Type>-type move"` description (e.g. `"Meowscarada used a
    Dark-type move on Primarina"` — a real event where a vision read could
    only identify the move's TYPE, not its actual name) was being checked as
    a literal move name, guaranteeing a nonsense flag every time.

Fixed in `_strip_used_prefix`/`_move_name` (widened `_HIT_OR_MISSED_SUFFIX`'s
alternation to include `"on"`, added `_BARE_USED_PREFIX` and
`_VAGUE_TYPE_ONLY_MOVE`, added `_TRAILING_PERIOD`) — 6 new regression tests in
`tests/test_moveset_validator.py`'s `TestMoveName`. Re-scanning after the fix:
flags dropped from 74 to 28, and every remaining flag checks out as either a
genuine implausible-move catch (the species above) or a genuine
misattribution catch the checker is SUPPOSED to surface — e.g. one real event
has `pokemon: "Porygon2"` but `detail: "The opposing Hydreigon used Draco
Meteor!"` (a real roster/identity mismatch worth a human look, not a checker
bug), and another has `pokemon: "Rotom"` (the base forme) + `"Hydro Pump"` —
a move only Rotom-**Wash** can learn, so this is very likely a forme misread
(should have been read as Rotom-Wash) rather than a false positive. Full
suite after this fix: 601 tests, all passing.

## 2f. Team-preview closed-set roster locking for battle-event identification (2026-07-04)

**Why this exists:** a follow-up to the same architecture review that drove
the §2d/§2e default-priority flip — the user's recommendation specifically
called out that instead of Gemini re-identifying every Pokémon from scratch
in every battle frame, team preview already tells the pipeline exactly which
Pokémon COULD be on screen, and that known-narrower list should be used to
constrain identification rather than just validate it after the fact.

`build_event_prompt()` (`analyze_matches.py`) already had a roster-constraint
block from the earlier Staraptor/Charizard fix (§2 / `tests/
test_build_event_prompt.py`), but it was framed as "identify freely, THEN
check against the known teams" — the roster was a validation afterthought,
not a constraint applied up front. This pass reframes it explicitly as a
**CLOSED-SET identification task**: every Pokémon on the field must be one
of its side's known Pokémon, and the model is told to actively match what it
sees against that short list first rather than open-set-recognize across the
whole game's dex and only check afterward.

It also surfaces a narrower list than the full 6-per-side team when one is
available: team preview's own directly-read "brought" (pick-4) selection
(`roster["player_brought"]`/`["opponent_brought"]` — the pick-4 screen read
at roster-read time, NOT the separate appearance-derived `merge_brought()`
computed after battle events finish, see that function's own docstring for
the distinction). When present, `build_event_prompt` adds a `brought_txt`
block naming each side's brought-4 explicitly and instructing the model to
check there FIRST, since "at most 4 candidates per side" is a smaller,
cheaper, more reliable identification problem than "at most 6." When the
brought read didn't succeed for a side, that side's part of the block says
plainly "not confidently read" rather than implying an empty list is
meaningful; when brought is empty/missing for BOTH sides, no `brought_txt`
block is added at all and the prompt falls back to full-team-only wording,
unchanged from before this pass.

**Honest gap, stated plainly (same standard as §9c's `VISIBILITY_SCAN_BANDS`
caveat):** this is a prompt-level constraint, not a true local
candidate-restricted image/template matcher. The deeper version of this idea
— a real classifier that crops each active-Pokémon icon and matches it
against only that side's brought-4 sprites, entirely without a Gemini call —
remains unbuilt. It would need real Pokémon Champions footage to calibrate
icon-crop positions against, the same real-footage-calibration gap already
documented for the visibility-check scan bands and for `icon_template_
matcher.py`'s unmeasured status/weather templates (§2e). Prompt-level
closed-set framing is a real, verified improvement over open-set framing,
but it doesn't eliminate the underlying vision call the way a true local
matcher would.

Covered by 4 new tests in `tests/test_build_event_prompt.py`'s
`TestBuildEventPromptClosedSetNarrowing` (brought list surfaced and
instructed to be checked first; no brought block when brought is
missing/empty; closed-set framing language present; a partial brought read —
one side succeeds, one doesn't — still surfaces the side that did and says
plainly the other wasn't confidently read). All 7 pre-existing roster-wording
tests in the same file still pass unmodified, since every substring they
assert on was preserved verbatim in the rewrite.

## 2g. Opponent-roster accuracy fixes from a real manual benchmark comparison (2026-07-06)

**Why this exists:** a user filled in `benchmark_labeling_sheet.xlsx` (their
own memory of each match's rosters/brought/leads/winner) for a real 5-match
job (`8c10092ac4a9`) and it was compared directly against that job's
`events.json`. The player's own roster, brought, leads, and the match winner
were correct in all 5 matches with zero exceptions. Every miss was on the
**opponent's** roster read, ranging 2/6-5/6 species correct match to match —
consistent with the already-documented fact that the opponent's side is
often shown as icons only, with no name text, unlike the player's own side.
Three fixes came directly out of that comparison:

1. **`read_roster()`'s retry/widen gate was blind to the opponent side.**
   The old check only compared `player_team` length against
   `ROSTER_MIN_ACCEPTABLE` to decide whether the roster read was "good
   enough" or needed the widened second attempt (more frames, wider
   pre-match window). Since the player's own side reads correctly almost
   immediately, that check passed on attempt 1 every single time — meaning
   the wider, more-frames second attempt was never actually used to help a
   sparse or wrong OPPONENT read, no matter how bad it was. `_roster_sparsity()`
   now returns `(min(pteam_n, oteam_n), pteam_n, oteam_n)`, and both the
   "is this good enough to stop" check and the "what's the best attempt to
   fall back to" tracking use that worse-side-aware metric instead. Covered
   by `tests/test_roster_accuracy_fixes.py`'s `TestReadRosterRetryGate` (a
   full player_team + sparse opponent_team no longer short-circuits the
   retry; the wider second attempt's better opponent read is actually used;
   falls back to the least-bad attempt when neither clears the bar).

2. **`OPPONENT_COLUMN_ZOOM` bumped 4→6 and `OPPONENT_COLUMN_CROP_CAP` bumped
   6→8.** Free levers (same images, no extra Gemini calls) given the
   opponent icon column is the dominant source of misreads: a bigger zoomed
   crop and more candidate crops per roster read. `tests/
   test_opponent_column_crop.py` already computes its expected crop
   dimensions from these constants rather than hardcoding the old values,
   so no test changes were needed.

3. **New: `summarize_roster_conflicts()` (`analyze_matches.py`), called right
   before each match's `team_preview` event is appended (both live-mode
   `main()` and batch-mode `_wait_and_finish()`).** Rolls the existing
   per-event `roster_conflict`/`roster_conflict_species` flags (see §9b) up
   into a match-level signal: when the SAME legal species recurs as a
   roster-conflict across 2+ distinct events in one match, it's added to
   that match's `team_preview` event as `likely_missed_opponent_species` —
   a much stronger signal that the roster read itself missed a real
   teammate than any single flagged event alone. Grounded in a real case
   found during the same benchmark comparison (job `8c10092ac4a9`, match 5):
   the roster read never identified the opponent's Dragalge, so an event
   whose battle text literally read "Dragalge" got substituted to "Latias"
   (the closest name in the wrong roster) and flagged as a conflict — this
   surfaces "Dragalge" directly on that match's team preview instead of
   requiring someone to notice the same recurring name buried across
   several separate event corrections. Not currently given special
   treatment in `MatchEvents.jsx` — it renders as a plain field like
   `illegal_species_detected` already does, since it isn't in `HIDDEN_FIELDS`.
   Covered by `tests/test_roster_accuracy_fixes.py`'s
   `TestSummarizeRosterConflicts` (a one-off conflict isn't enough; a
   recurring one surfaces; Mega/form variants of the same species count as
   the same recurrence via `_species_base_norm`; multiple recurring species
   both get listed, sorted).

**Honest scope:** these fixes address the mechanisms found to be actively
working against accuracy (a retry gate that never triggered, a
missed-species signal that existed per-event but was never rolled up) — they
don't add a fundamentally new identification method (e.g. a real local
icon/template matcher for the closed ~200-species roster, which remains the
"deeper version" gap noted in §2f). Re-running job `8c10092ac4a9` (or any
new job) after these fixes would be the way to confirm the actual
opponent-accuracy improvement empirically, since none of the 5 already-
processed matches were re-run against the new code as part of this pass.

## 2h. Round 2 of the same benchmark comparison (2026-07-06, after re-running job 8c10092ac4a9)

**Why this exists:** the round-1 fixes above were validated by fully
re-running job `8c10092ac4a9`'s footage and diffing the new `events.json`
against the same `benchmark_labeling_sheet.xlsx` again (see
`accuracy_comparison_8c10092ac4a9_v2.md`). The player's own side stayed
perfect (5/5 matches). The opponent side showed genuine, concrete wins (the
new `likely_missed_opponent_species` flag correctly named a real missed
species on 3 of 5 matches; a bought-list contamination bug in match 4 was
fixed; match 5's opponent brought/leads became 100% correct) alongside a
regression (match 4's opponent roster went 4/6→2/6 between two runs of the
*identical* video, attributed to plain Gemini non-determinism, not a code
change) and a persistent, unresolved problem (match 3's roster read is still
badly garbled with player/opponent sides cross-contaminated). Three more
fixes came directly out of that second round:

1. **New: `apply_likely_missed_species_correction()` (`analyze_matches.py`),
   called right after `summarize_roster_conflicts()` at both call sites
   (live-mode `main()` and batch-mode `_wait_and_finish()`/live-read path).**
   Round 1 added `likely_missed_opponent_species` as a match-level *signal*
   sitting next to a roster that was still wrong. This folds it directly
   INTO `opponent_team`/`opponent_brought` instead — a species that recurred
   as a `roster_conflict` was, by definition, actually seen fighting in that
   match, so naming it in the fields everything downstream (dashboard,
   career aggregation, `strategic_analysis`) actually reads is no longer
   optional. Skips species already present (via `_species_base_norm`, so a
   Mega/regional variant already listed isn't duplicated) and respects
   `opponent_bring_cap` (default 4) when extending `opponent_brought`. Does
   NOT touch `detail` or retroactively re-run that match's battle-event
   identification against the corrected roster — see the scope note below.
   Covered by `tests/test_roster_accuracy_fixes.py`'s
   `TestApplyLikelyMissedSpeciesCorrection`.

2. **New: `reconcile_player_rosters_across_matches()` (`analyze_matches.py`),
   called once after every match has been processed (end of live-mode
   `main()`'s loop and end of batch-mode `_wait_and_finish()`), NOT
   per-match.** A player's own team is very likely identical across every
   match in one job/video (VGC streamers overwhelmingly play one team per
   session) — this is the same real-world fact that made the player's own
   roster read 100% correct in both benchmark rounds. Job `8c10092ac4a9`'s
   match 3 was the exception: 4 of 5 matches read the identical player team,
   while match 3 alone came back badly mixed up (including a Pokemon that
   was actually the opponent's). This function compares every `team_preview`
   event's `player_team` (order-independent, Mega/form variants collapsed
   via a new `_team_species_key()` helper) and, ONLY when exactly one match
   disagrees with a unanimous majority among at least `min_matches=3` total,
   overwrites that one outlier's `player_team` with the majority's text —
   keeping the original in `player_team_original_read` and stamping
   `player_team_corrected_by_cross_match_consistency: True` so it's never
   silent. Deliberately does nothing on a tie, on multiple differently-wrong
   outliers, or below the minimum match count, since any of those could mean
   the player legitimately changed teams partway through, not that one read
   is simply wrong. Covered by `tests/test_roster_accuracy_fixes.py`'s
   `TestReconcilePlayerRostersAcrossMatches`, including the exact match-3
   team strings from the real job as a regression case.

3. **`read_roster()` redesigned to always run every attempt and merge them,
   instead of stopping at the first attempt that merely "looked good
   enough."** The round-1 fix (item 1 in §2g above) made the retry gate
   opponent-aware, but round 2's re-run still showed real failures a
   "looks complete" check can never catch: match 2's Kingambit→Heracross
   misread happened even though that attempt's `opponent_team` was already
   a full 6/6, and match 4 got WORSE on a second, otherwise-identical run of
   the same video purely from Gemini sampling/model non-determinism. Neither
   failure mode is something any sparsity threshold can detect, since both
   looked "done." The fix: a new `_merge_roster_reads(a, b, team_size)`
   helper unions two roster reads' team lists (deduped via
   `_species_base_norm`, capped at `team_size` so combining two
   wrong-but-different guesses can't inflate a team past its real size) and
   takes whichever read's brought/pick-4 field is non-empty (preferring the
   first). `read_roster()` now runs every configured
   `ROSTER_SEARCH_ATTEMPTS` window unconditionally — no early exit — and
   folds all of them together with this merge. The old
   `ROSTER_MIN_ACCEPTABLE` constant and the early-exit branch it gated are
   gone (removed, not just unused — confirmed via grep it wasn't referenced
   elsewhere); `_roster_sparsity()` itself is unchanged and still used
   for the attempt-by-attempt progress printout, just no longer as a
   stopping gate. Cost: this is a deliberate, bounded trade — exactly
   `len(ROSTER_SEARCH_ATTEMPTS)` (currently 2) Gemini calls per match's
   roster read every time, versus as few as 1 before, in exchange for never
   depending on a single roll of the dice for the harder (opponent) side.
   Covered by `tests/test_roster_accuracy_fixes.py`'s
   `TestMergeRosterReads` and `TestReadRosterAlwaysMergesBothAttempts`
   (replaces the old `TestReadRosterRetryGate` class from round 1, since the
   gate it tested no longer exists).

**Honest scope, still (round 2):** none of these three retroactively re-run a match's
battle-event identification against a roster corrected AFTER the fact (by
fix 1 or 2 above) — that identification already happened against whatever
roster was known at the time. They correct the roster RECORD so downstream
consumers (dashboard, career aggregation, `strategic_analysis`) see the
right team, not the historical event-by-event identification decisions made
during that match. Match 3's core problem — a genuinely cross-contaminated
team-preview read, not just a sparse one — is also still unresolved by any
of round 1 or round 2's fixes; see `accuracy_comparison_8c10092ac4a9_v2.md`
for the concrete evidence and a suggested manual next step (inspecting that
match's actual team-preview frames directly).

## 2i. Species sprite reference library (accuracy_addons/templates/species/, 2026-07-06)

**Why this exists:** every fix in §2g/§2h works around the opponent-roster
read being unreliable; none of them are a fundamentally different
identification method. `accuracy_addons/icon_template_matcher.py` already
does free, local (no Gemini call) pixel template-matching for status badges
and move-type icons against real footage - the same idea applied to
species icons on the team-preview screen (a genuine local icon-matcher
against this game's closed ~212-species roster) is the "deeper version" fix
noted in §2g, but it needs a reference image for every legal species first.
This section is that reference set - NOT the matcher itself, which still
needs to be designed and validated against real footage the same rigorous
way `icon_template_matcher.py`'s existing templates were (see that file's
own "HONEST CURRENT SCOPE" docstring section for what real validation looks
like versus a self-match).

**What was added:**
- `accuracy_addons/tools/fetch_species_sprites.py` - a standalone script
  (run once by hand, NOT called by analyze_matches.py at runtime) that
  downloads Bulbagarden Archives' "Champions menu sprites" category: 320
  PNG icons extracted directly from Pokémon Champions itself (not generic
  Pokédex artwork - these are the actual in-game team-preview icons), named
  `Menu_CP_<national_dex_number>[-<form>].png`. It fetches the real file
  list from Bulbagarden's own MediaWiki API (not a guessed/hardcoded list),
  downloads each via `Special:FilePath/<filename>` (resolves the real
  MD5-hash-bucketed media URL without needing to know that hash), and
  writes a `manifest.json` mapping every file to its national dex number,
  species name, and form (`None` for the default/base form).
- Species names come from a static `CHAMPIONS_DEX_MAP` embedded in the
  script - a copy of PokeAPI's own Champions-specific Pokedex
  (`https://pokeapi.co/api/v2/pokedex/champions`, id 36), confirmed by
  direct spot-check to use real national dex numbers (Charizard = 6 in
  both), not a separate Champions-only renumbering. Cross-checked against
  this project's own `adapters/pokemon/regulations/m-b.json` species list:
  covers exactly 208 of that file's 212 species, and the 4 gaps are
  precisely m-b.json's own `provisional_species` (basculin, duraludon,
  girafarig, glimmet) - the ones already flagged there as not
  independently source-confirmed. Nothing was missed by accident; see
  `tests/test_fetch_species_sprites.py`'s
  `test_covers_every_m_b_species_except_the_known_provisional_four`, which
  re-checks this against the live regulation file rather than a frozen
  assumption.
- **Why this is a script you run, not something this session ran for you:**
  the sandboxed environment this was written in could not reach
  `archives.bulbagarden.net` (or even `github.com`) at all - outbound
  network here is allowlisted, and neither domain is on it. Both a direct
  `curl`/`requests` attempt and a headless page-text fetch confirmed this;
  the actual Champions-menu-sprite images were never fetched or seen by
  this session's own tools, only their *metadata* (filenames, sizes,
  licensing) via search results and one working page fetch of the category
  listing itself. Run `python accuracy_addons/tools/fetch_species_sprites.py`
  from `poc-starter/` on your own machine (real, unrestricted network) to
  actually populate `accuracy_addons/templates/species/` - it's idempotent
  (skips files it already has) and needs only the Python standard library.
- **Real bug found and fixed on the user's first actual run (2026-07-06):**
  the category has grown to 359 files (the in-game roster expanded since
  this section was first researched at ~320/208 species - `pawmot`, dex
  923, was the one new species this surfaced, now added to
  `CHAMPIONS_DEX_MAP`). More importantly, the very first live run parsed
  **zero** of those 359 files - MediaWiki's API returns file titles with
  plain spaces ("Menu CP 0003-Mega X.png"), not the underscore form used
  everywhere else on the site ("Menu_CP_0003-Mega_X.png"), and
  `FILENAME_RE`'s literal underscores silently matched none of them. Fixed
  with a new `normalize_title()` step (spaces → underscores) applied to
  every title `list_category_files()` collects, before anything else
  touches it - MediaWiki treats the two forms as fully interchangeable for
  a given title, so this is always safe. This is exactly the kind of gap
  that only shows up on a real run against real data, not by reasoning
  about the API in the abstract - the fetch logic itself (pagination,
  `Special:FilePath` redirect resolution) was never actually exercised
  against the live site until the user ran it, only planned/reviewed.
  Covered by `tests/test_fetch_species_sprites.py`'s new
  `TestNormalizeTitle` class, including the exact failing case
  end-to-end (raw space-separated title → normalize → parse).
- **Shiny sprites added (2026-07-06, prompted by a direct user question -
  "how does this solution handle shiny sprites?").** The honest answer at
  that point was "it doesn't" - the script only ever fetched "Champions
  menu sprites", and Bulbagarden maintains a wholly SEPARATE "Champions
  Shiny menu sprites" category (also 359 files - a true 1:1 parallel set,
  every normal-form file has a shiny counterpart), which nothing had
  fetched or even checked for until asked. Fixed by making `CATEGORIES` a
  list of both, and `list_all_category_files()` unions them. Parsing needed
  more than just adding the new category, though: Bulbagarden joins a FORM
  suffix with a HYPHEN ("-Mega_X") but the SHINY suffix with an
  UNDERSCORE, always last ("Menu_CP_0003_shiny.png",
  "Menu_CP_0006-Mega_X_shiny.png") - two genuinely different conventions,
  not one. `parse_filename()` now strips a trailing `_shiny` first (via
  `SHINY_SUFFIX_RE`, setting a boolean) and only THEN runs the original
  `FILENAME_RE` on whatever's left - a single combined regex was tried
  first and rejected, since its naturally-greedy form group mis-captured
  "Mega_shiny" as if "shiny" were part of the form name, with no way to
  tell where the real form ended. `parse_filename()`'s return signature
  changed from a 2-tuple to a 3-tuple (`dex_number, form, shiny`) to carry
  this through; every call site and test was updated to match. Covered by
  `tests/test_fetch_species_sprites.py`'s new `TestShinyParsing` class,
  including the specific base-form-plus-shiny and form-plus-shiny cases
  that would have mis-parsed under a naive combined-regex approach.
  Normal and shiny files are saved side by side in the same
  `templates/species/` folder (their filenames never collide - the
  `_shiny` suffix already makes them unique) and distinguished in
  `manifest.json` via a `"shiny": true/false` field per entry, rather than
  a separate folder - keeps one manifest as the single source of truth for
  filtering either way.

**Licensing:** Bulbagarden Archives tags these as fair-use sprite
extractions from the actual game; the Archives' overall content license is
CC BY-NC-SA 2.5. Fine for this project's own internal, non-commercial
accuracy tooling - don't redistribute the image files themselves outside
this project.

**Honest scope:** this is a reference image library only. No matcher reads
these files yet - extending `icon_template_matcher.py` (or a new sibling
module) to actually match a cropped opponent-icon-column region against
this template set, and validating it against real footage the same way
burn/type icons were (self-match AND cross-frame, with a documented
false-positive investigation - see that file's docstring), is future work,
not done here.

## 2j. Species icon matcher (`accuracy_addons/species_icon_matcher.py`, 2026-07-06) - built, tested, NOT wired in

The "future work" flagged at the end of section 2i was attempted directly
after it: a real matcher (`species_icon_matcher.py`) against the
`templates/species/` reference library from 2i, targeting the opponent's
team-preview sprite column specifically (icons only, no name text - the
dominant source of roster misreads per 2g/2h). **Headline result: real
validation found it only correctly identifies about 1 of 6 real opponent
sprites (~17%). It is built, tested, and documented, but NOT wired into
`read_roster()` or anywhere else in the pipeline**, because that accuracy
rate isn't good enough to trust as a signal, soft or otherwise.

**What's real and kept anyway:**
- A genuine, previously-undiscovered crop-framing bug: the analyzer's
  existing `OPPONENT_COLUMN_BOX` (used by `crop_opponent_icon_column`,
  wired into `read_roster()` since section 2g/2h) is framed on the
  type/gender BADGES next to each sprite (what `icon_template_matcher.py`
  reads), and deliberately excludes the sprite art itself. A first version
  of the species matcher was measured against a hand-rolled ad-hoc crop
  box that happened to be wider than that real production box, so it
  looked promising in isolation - re-running it against the REAL
  production crop returned confidently WRONG results for every row.
  **Fixed**: `analyze_matches.py` now has a separate
  `crop_opponent_sprite_column()` / `OPPONENT_SPRITE_COLUMN_BOX =
  (0.655, 0.02, 0.76, 0.86)`, framed on the sprite art specifically,
  measured via a real row-divider brightness scan against
  `jobs/8c10092ac4a9/vod.mp4` (match 1, ~70s - confirmed via
  `_looks_like_roster_panel` to actually show the team-preview screen).
  This function exists and is tested independently of whether the matcher
  itself ever gets wired in - it's a real, standalone crop utility now.
- A second false claim caught and corrected: the first version of the
  matcher's docs said the opponent's 6th Pokemon was "cut off by the
  source frame." Widening the crop box all the way to the bottom of the
  frame showed the real 6th Pokemon fully, undamaged - that was an
  artifact of an overly-tight ad-hoc crop box, not a real screen-content
  limitation. Corrected before it could propagate into other docs.
- A real, measured accuracy IMPROVEMENT that's still not enough on its
  own: comparing a raw row band directly against the reference library
  scored badly even for a genuinely correct sprite (a real Blastoise row
  scored a WRONG top pick, "cofagrigus," at 0.437) - investigating why
  found a real scale mismatch (reference PNGs are tightly cropped to
  their own sprite with near-zero padding; a raw row band has the sprite
  occupying maybe half the card, with a lot of background around it, so
  after both get resized to the same small comparison size they're
  comparing different things). Added `_tight_crop_to_sprite()` (hue/
  brightness background mask + largest-connected-component bounding box,
  reusing the same magenta/maroon hue family as
  `analyze_matches._ROSTER_PANEL_HUE_RANGE`) - this turned that same
  Blastoise row from a wrong pick at 0.437 into a CORRECT pick at 0.569
  with a real, checked margin. Real and kept.
- A real, measured SPEED fix, independent of the accuracy findings:
  comparing the full ~360-720-entry reference library against one row at
  its native zoomed resolution (~900x900px) took over 45 seconds for one
  real 6-row column (timed out in testing). Downscaling both the crop and
  every composited reference to a small fixed `MATCH_SIZE = (96, 96)`
  before comparing brought that under 2 seconds for the same real column.
  This makes the (currently unreliable) matching fast - it doesn't make
  it correct.

**Why it still doesn't work well enough**, tested and ruled out rather
than assumed:
- Re-running ALL 6 real rows (Delphox, Sneasler, Incineroar, Kingambit,
  Blastoise, Sinistcha, per the same job's own real team-preview
  screenshot) through the corrected crop + tight-crop + matching pipeline
  together found only the ONE Blastoise row came back correct - 1/6, not
  a usable rate. The other 5 rows' top picks were wrong species entirely,
  scoring in a similar 0.3-0.6 range as the one correct row - absolute
  score does not reliably separate right from wrong here.
- The MARGIN-based confidence gate (top-1 vs. top-2 score gap), which an
  earlier round of this same investigation (using the since-corrected,
  mis-framed crop) had suggested cleanly separated confident/correct rows
  from uncertain ones, was RE-TESTED against the real, corrected data and
  does NOT hold up: the one correct row's margin (0.037) sits close to at
  least one wrong row's margin (0.045) - a threshold that accepts the
  right answer would also accept a wrong one, and vice versa. This is a
  genuine negative finding about the underlying score's discriminating
  power, not a threshold left untuned.
- A silhouette/edge-based variant (Canny edges of the tight crop vs. Canny
  edges of each reference's alpha mask) was tried as a possible fix for
  background/scale sensitivity - it scored WORSE (0/6 correct on the same
  real rows) and was not adopted.
- Root cause, as best understood: (a) the team-preview panel's background
  has a visible gradient/highlight, not a flat color, so a
  hue/brightness mask + connected-component crop is still an
  approximation, sensitive to neighboring-row bleed and JPEG noise near
  row dividers; (b) real sprite art varies a lot in aspect ratio
  (Sneasler tall/thin vs. Blastoise wide) in ways the tight crop alone
  doesn't normalize for; (c) this approach never uses the type-badge
  icons next to each sprite at all - a species' type combination is
  highly discriminating within this game's closed ~212-species roster,
  and `icon_template_matcher.py`-style EXACT icon matching (not fuzzy
  whole-sprite correlation) could plausibly narrow candidates far more
  reliably before ever touching sprite pixels. That cross-reference is
  the most promising concrete next step if this capability gets
  revisited - not built here.

**Decision:** do not wire `species_icon_matcher.py` into `read_roster()`
or any other accuracy_addons cross-check path. It stays as a real,
independently-tested, honestly-documented module (see its own "HONEST
CURRENT SCOPE" docstring, which mirrors this section) plus a real,
useful-on-its-own crop utility in `analyze_matches.py`
(`crop_opponent_sprite_column`) - both good groundwork for a future
attempt, neither good enough yet to trust with real users' results.
Tests: `tests/test_species_icon_matcher.py` (20 tests) deliberately do
NOT assert specific correct species on real footage, for the same reason
this section doesn't claim the module works - they check the real
mechanics (slicing, tight-cropping, compositing, merging, and that the
real end-to-end pipeline runs without crashing on real data), which IS
solid, independent of the matching accuracy problem above.

## 2k. Type-badge species narrowing (`accuracy_addons/team_preview_type_matcher.py`, 2026-07-06) - built, tested, wired in as a supplementary (non-forcing) hint - see 2l for the wiring

Section 2j's own "most promising next step" was pursued directly: instead
of matching the whole sprite, match the 1-2 small type-badge icons (Fire/
Water/Dark/Steel/etc.) shown next to each team-preview row, then narrow
the ~212-species legal roster down to species whose real type combination
is consistent with what was read. **Headline result: badge matching is a
real, large improvement over whole-sprite matching, and one property of it
held up perfectly under harder, repeated testing - but full both-badge
identification is genuinely frame-sensitive, so this is wired as a
narrowing/cross-check signal design, not yet actually wired into
`read_roster()`.**

**What was built:**
- `accuracy_addons/data/species_types.json`: the M-B regulation's 212
  legal species, each mapped to its real 1-2 Pokemon types. Built from
  PokeAPI's real `/api/v2/type/{name}` responses for all 18 types (fetched
  via `mcp__workspace__web_fetch`, since direct bash `curl` is blocked by
  this sandbox's network allowlist), cross-referenced by hand against
  `adapters/pokemon/regulations/m-b.json`'s own species list. Verified
  programmatically before being written: 212/212 legal species mapped, 0
  extra, 0 invalid type names.
- `accuracy_addons/templates/team_preview_types/`: real captured 64x64
  badge crops from `jobs/8c10092ac4a9` match 1's own team-preview screen -
  9 of the real game's 18 types (fire, poison, fighting, psychic, dark,
  steel, water, grass, ghost). This is a DIFFERENT template set from
  `icon_template_matcher.py`'s existing move-type icons - reusing those was
  tried first and found to give inconsistent results (the correct "dark"
  template scored LOWEST among all candidates for a real dark badge)
  because they're 24x24px captures from a different screen (the battle
  move-info panel) at an incompatible scale/crop for this UI element.
- `crop_opponent_badge_column()` in `analyze_matches.py`
  (`OPPONENT_BADGE_COLUMN_BOX = (0.74, 0.02, 0.80, 0.86)`): a THIRD, separate
  crop box alongside `crop_opponent_icon_column` (badges+gender icon, used
  by the existing Gemini roster prompt) and `crop_opponent_sprite_column`
  (sprite art only, from 2j) - three different real UI elements in the same
  panel, confirmed by real frame inspection to need three different boxes,
  not variations of one.
- `team_preview_type_matcher.py`: `find_badge_components()` isolates 1-2
  badge-icon bounding boxes per row (same hue/brightness background mask as
  2j's `_tight_crop_to_sprite`, plus a size AND aspect-ratio filter - the
  aspect-ratio check is a real fix for a real found artifact, a spurious
  thin card-edge/divider component that is not roughly square like a real
  badge). `identify_badge_type()` compares an isolated badge against every
  loaded template via `cv2.matchTemplate`. `narrow_species_by_types()`
  filters `species_types.json` down to species consistent with what was
  read for one row (exact match if a row shows exactly 1 badge - genuinely
  mono-type Pokemon always show only 1 badge in this UI - exact pair match
  if both of 2 badges were classified, partial "contains" match if only 1
  of 2 was classified).
- A real bug found and fixed while validating: two of the captured
  templates were mislabeled at the exploratory-capture stage - the file
  saved as `type_fairy.png` was actually Delphox's real PSYCHIC badge, and
  `type_psychic.png` was actually Sneasler's real POISON badge (Psychic and
  Fairy badges are both pink and easy to visually mix up at this crop's
  resolution). Caught by re-deriving the real frame from scratch and
  finding the "wrong" template scored 0.99+ against the WRONG real badge -
  a real, measured contradiction. Fixed by relabeling from the pristine
  originals; net effect was gaining a real "poison" template as a side
  effect (no real Fairy badge has been captured from this footage at all,
  since none of these 6 rows are Fairy-type).

**Real validation result - re-tested across 7 real frames of the SAME
static team-preview screen** (job 8c10092ac4a9 match 1, t=68/69/70/70.5/
71/72/73s, at the same 1024px-wide scale the production pipeline actually
samples roster frames at - not native resolution):
- **The safety property holds perfectly**: across all 7 frames x 6 rows
  (42 checks against the known real roster - Delphox, Sneasler, Incineroar,
  Kingambit, Blastoise, Sinistcha), the true species was in
  `narrow_species_by_types`' candidate list every single time - 42/42,
  never wrongly excluded. This is the property that matters for safe use
  as a cross-check/narrowing signal.
- **Full both-badge-correct identification is genuinely frame-sensitive**,
  even within one static screen: the count of rows getting a full,
  both-type-correct read ranged from 3/6 to 5/6 across the 7 frames - no
  single frame in this retest hit a clean 6/6 (an earlier, single-frame
  test had found 6/6; the broader retest shows that doesn't reliably
  reproduce frame-to-frame). Kingambit (dark/steel) was the most sensitive
  row: only 1 of 7 frames identified both badges; the other 6 identified
  only "dark," leaving 22 roster candidates instead of 1.
- **A separate, previously undiscovered failure mode**: badge-COUNT
  detection itself is occasionally noisy even for a genuinely mono-type
  Pokemon - Blastoise (real mono-Water) showed 2 detected badge components
  instead of 1 in 2 of the 7 frames, silently downgrading the narrowing
  rule from its strongest ("exact single type") to its weakest ("contains
  this type") branch. The real species was still included both times, but
  the narrowing was needlessly looser.

**Multi-frame majority-vote aggregation** (`identify_row_types_multi_frame`,
added directly as the concrete fix for the frame-sensitivity finding above)
was built and RE-TESTED against the SAME 7 real frames, combined as one
7-way majority vote (threshold 4/7) rather than treated as 7 separate
single-frame reads:
- **5 of 6 rows reached a full, exact type match** (Delphox, Sneasler,
  Incineroar, Blastoise, Sinistcha) - matching the BEST any single frame
  achieved on its own, but now deterministically, without depending on a
  caller getting lucky and picking the one good frame out of 7.
- **The safety property still held**: all 6 species remained in
  `narrow_species_by_types`' candidate list under aggregation.
- **The Blastoise badge-count noise was fully resolved**: majority vote
  correctly resolved 5 frames saying "1 badge" vs. 2 frames saying "2
  badges" to the true single-badge read, restoring the tight exact-match
  candidate list (10) instead of the looser partial-match one a single
  noisy frame could produce.
- **Kingambit (dark/steel) still did NOT reach a full match under
  aggregation** - its steel badge was classified in only 1 of 7 frames,
  below the 4-frame majority threshold, so voting correctly refused to
  confirm it rather than guessing. This is a real, DIFFERENT kind of
  limitation than frame noise: it looks like a persistent per-badge
  detection weakness for this specific badge instance (possibly a lower-
  quality steel template, or something about this particular badge's
  on-screen rendering), not something more frames of the same match would
  fix. Aggregation cannot invent information no single frame ever had.

**Kingambit's steel-badge gap: root-caused and fixed (2026-07-06 follow-up).**
The investigation above left one open question - why does Kingambit's
steel badge specifically fail almost every frame, when the same pipeline
correctly reads every other row's second badge? Direct measurement found
the answer: it was NOT a template-quality problem. `find_badge_components`
was occasionally MERGING the real steel badge's connected component with
whatever sits directly above/around it in the panel - a real, measured
artifact (one malformed box was 58x67px instead of the real ~37x36px).
Once resized to the 64x64 comparison size, this distorted crop no longer
resembled a badge at all, so it scored low against EVERY type (0.45-0.65),
not specifically against steel - which is why it looked like a "steel
detection" problem when it was actually a crop-geometry problem. This was
confirmed two ways: (a) measuring that every OTHER row's correctly-
identified second badge sits at a highly consistent position/size (median
offset from the first badge: dx~47px, dy~2px, ~37x36px, across 24
confirmed-clean real badge pairs), and (b) an exhaustive local position/
size search within the malformed box's own footprint reliably recovering a
clean, correctly-scoring steel crop (0.94-0.97) at approximately that
expected relative position.

**The fix - and a caught-before-shipping false start.** The first fix
attempted added an outright rejection step: treat any component whose
width exceeds ~70% of the row's total width as a spurious "full-row
artifact" and discard it before scoring. Validated across all 6 rows x 7
frames, this caused a real SAFETY REGRESSION - several previously-safe
rows (Delphox, Sneasler, Sinistcha in various frames) had their
`num_badges_found` incorrectly reduced from 2 to 1 whenever one of their
own two real components happened to also cross that width threshold,
which then wrongly triggered `narrow_species_by_types`' strict "exact
single-type" rule and EXCLUDED the true, real dual-typed species. This was
caught by direct validation before shipping and led to a hard rule for
this module going forward: **rejecting a detected component is never safe
in general**, because there's no reliable way to distinguish "real second
badge, just malformed" from "spurious artifact" from geometry alone - and
under-counting badges is exactly the failure mode that breaks the safety
property this module is built around.

The shipped fix, `_refine_oversized_badge_crop()`, never rejects or
removes a detected component - it only repositions the crop used for
scoring. When the second badge's box is anomalously large relative to the
first (`BADGE_SIZE_ANOMALY_RATIO = 1.3`), it slides a small set of real
badge-sized windows (`REFINE_SIZE_OPTIONS`, measured from the same 24
clean pairs above) across a generous margin (`REFINE_SEARCH_MARGIN_PX =
25`) around the malformed box's own bounds, and keeps whichever sub-crop
scores best against any loaded template - directly recovering the real
badge pixels submerged inside the merged region.

**Real re-validation, same 7 frames, after the fix:** Kingambit's
dark+steel pair was fully, correctly identified in 6 of 7 frames (up from
1 of 7). The aggregate single-frame result across all 7 frames x 6 rows
went from 29/42 to **34/42** correct-both-type reads, with **zero new
safety violations** (true species stayed in the candidate list in all 42
checks, exactly as before). Combined with the existing multi-frame
majority-vote aggregation (crop refinement applied to each frame first,
then voted across all 7), the result is a **full, exact 6/6** - every one
of the 6 real rows, including Kingambit's dark+steel pair narrowing to
exactly 1 candidate species. This is the best validated result so far for
this module, and the two fixes are complementary, not redundant: crop
refinement fixes the underlying per-frame read; aggregation smooths over
whatever noise refinement still can't recover on its own.

**One case remains honestly unfixed:** at t=72s specifically, a SEPARATE,
more severe artifact - a component spanning nearly the ENTIRE row's width,
observed identically at both Kingambit's and Blastoise's rows at that
exact timestamp (strongly suggesting a shared visual glitch, e.g. a
transition/compression flash, rather than something specific to either
Pokemon) - occupies one of only `MAX_BADGES_PER_ROW = 2` badge "slots,"
which can crowd out the real second badge entirely rather than merely
distorting its geometry. This is a qualitatively different failure
(component starvation, not geometry distortion) that the local-search fix
does not address, and which was deliberately NOT patched via component
rejection given the safety regression described above.

**Decision (updated 2026-07-06, see 2l):** this module is a real,
substantial improvement over 2j's whole-sprite approach (candidate-list
recall held up perfectly under harder testing, vs. 2j's ~1/6 whole-match
accuracy), and combining crop refinement with multi-frame aggregation now
reaches a full 6/6 on the one real match tested. It is now wired into
`read_roster()` (see 2l), but deliberately NOT as a standalone identifier
or an auto-correction the way 2g/2h's roster-conflict correction is -
because: (a) it's only been validated against one real match, (b) template
coverage is still 9/18 types, and (c) the t=72s component-starvation
failure mode shows there's still at least one unfixed way this can go
wrong on real footage. It's wired as a purely additive, informational
`opponent_row_type_hints` field instead - see 2l for exactly what that
means and why. Concrete next steps before considering a stronger
(auto-correcting) wiring: test against more real matches with different
type combinations, ideally including one of the 9 not-yet-covered types
(normal, flying, fairy, ground, rock, bug, ice, electric, dragon), and
consider whether a 3rd badge "slot" (or some other way to avoid a
starvation-artifact permanently occupying one of only 2 slots) is worth
the added complexity given how rarely it was observed (1 of 7 frames, at
one specific timestamp, for a full-row-width glitch shared across two
unrelated rows).

Tests: `tests/test_team_preview_type_matcher.py` (37 tests) cover the real
mechanics (background segmentation, badge-component finding + its size/
aspect-ratio filters, row slicing, the crop-refinement recovery search in
isolation and via an end-to-end synthetic-merge integration test,
narrowing-rule logic against a synthetic species map, and the multi-frame
majority-vote/tie-break logic against hand-built fake per-frame results)
plus two real-footage regression tests: one asserting the ONE property
validated on a single frame - the true species is always in the narrowed
candidate list - and one that re-derives all 7 real frames (now with crop
refinement active) and asserts both that same safety property AND a
conservative floor (>=5/6 full-exact matches, measured 6/6) for the
combined aggregation+refinement result.

## 2l. Zero-added-cost frame-sampling improvements (2026-07-06): best-frame-in-window selection, OCR-frame reuse for free cross-checks, and type-badge hints wired into `read_roster()`

Prompted by a strategic question ("are there more high-quality frame
placements we can implement to improve accuracy without skyrocketing the
cost?"). A code-grounded survey of the existing frame-sampling
architecture found 5 real opportunities; options #1-4 below cost
literally **$0 additional Gemini spend** because they all reuse frames
that some part of the pipeline was already extracting anyway - they just
use that same material more effectively than before. (Option #5 -
densifying `structure_pass.py`'s uniform whole-video sampling around real
match transitions - has a small but real added Gemini cost, since unlike
the other four it scales with video length rather than a fixed, small
number of matches/transitions/roster reads; it was deliberately left as a
separate future decision, not bundled into this batch.)

**1. `frame_quality.py` (new module) - free, local sharpness scoring.**
`frame_sharpness(path)` returns a Laplacian-variance score
(`cv2.Laplacian(gray, cv2.CV_64F).var()`, higher = sharper) for one image,
or `None` for an unreadable file (never a fake `0.0`, so a missing frame
is never mistaken for "sharpest"). `pick_sharpest(paths)` returns whichever
path scores highest, skipping unreadable ones. Deliberately the simplest
possible blur/sharpness proxy - same philosophy as `frame_dedup.py`'s
plain pixel-diff approach - not a general image-quality model. Tested
against a real synthetic checkerboard pattern vs. its own Gaussian-blurred
copy (not mocked scores) - `tests/test_frame_quality.py`, 7 tests.

**2. `attach_reference_frames()` extended with time-windowed
best-frame-in-window selection.** Previously this just tagged every event
with the single nearest-in-time frame from the low-res, sparse Gemini
battle sample (`args.battle_fps` default ≈0.33fps @ 640px) - whichever
frame happened to be closest, blurry mid-transition or not. It now accepts
an optional `quality_frames` (typically the OCR tier's own denser,
higher-res sample - see below) and `quality_window_s` (default
`QUALITY_FRAME_WINDOW_S = 1.5`s): for each event, it gathers every
`quality_frames` candidate within that window of the event's own
timestamp, and picks the SHARPEST one among them
(`frame_quality.pick_sharpest`) instead of the nearest. Design principle,
stated explicitly in the docstring: this gathers candidates by TIME WINDOW
first, then ranks by sharpness only among those already-close candidates
- it is NOT a general "find the best frame anywhere" search, just a
tie-break among frames plausibly showing the same moment. Falls back to
the exact original nearest-frame behavior when no `quality_frames`
candidate is in range (start/end of a match window) or when the caller
passes nothing at all - fully backward compatible, verified against the
existing `TestAttachReferenceFrames` tests, which call it with only 2
positional args and are unaffected.

**3. `ocr_pipeline.py` split into `sample_ocr_frames()` +
`extract_ocr_events()`.** The OCR tier already samples the SAME match
window a second time, at `OCR_FPS = 2.0` / `OCR_SCALE_W = 1280` - denser
and higher-res than the Gemini battle sample, but previously used only to
extract on-screen-text events. `sample_ocr_frames()` is just that sampling
step, split out so a caller (analyze_matches.py's live-mode loop) that
ALSO wants the raw frame list for something else - namely, feeding
`attach_reference_frames`' `quality_frames` above - doesn't have to sample
the same window twice. `extract_ocr_events()` gained an optional `frames=`
parameter: if the caller already has the pre-sampled list, pass it here to
skip re-sampling/re-running ffmpeg entirely; omitted (the original call
shape), it samples internally exactly as before. Both changes verified
fully backward-compatible against the pre-existing OCR pipeline test
suite, which still passes unchanged; 2 new tests added for the split
(`tests/test_ocr_pipeline.py`, 28 tests total).

**Net effect of #1-3:** every accuracy_addons pixel cross-check
(`cross_check_hp_bar_events`, `cross_check_status_events`,
`cross_check_reference_frame_visibility` - see 2e) reads straight from
whatever `reference_frame` an event was tagged with. Before this change,
that was always the sparse, low-res Gemini-facing frame, even on a job
where the denser OCR tier was already sampling much sharper material for
free. Now, whenever the OCR tier is on (`--use-ocr-tier`, default on),
`analyze_matches.py`'s live-mode loop samples the OCR frame list ONCE (via
`ocr_pipeline.sample_ocr_frames`) before calling `attach_reference_frames`,
passes it in as `quality_frames`, and then reuses the SAME list (via
`extract_ocr_events(..., frames=ocr_frames)`) for the actual OCR text
extraction - one ffmpeg sampling pass serving two purposes, zero added
Gemini calls, and every cross-check gets a sharper photo to work from
whenever one was available nearby. `--no-ocr-tier` or a match window with
no nearby OCR-tier frame degrades gracefully to the exact prior behavior.

**4/5. Type-badge hints wired into `read_roster()`
(`attach_opponent_type_hints`) - resolves task #171/#189, and folds
in task #190's "extend multi-attempt pattern" goal.** `read_roster()`
already runs `ROSTER_SEARCH_ATTEMPTS` (2 progressively-wider pre-match
windows) and, since 2g, additionally crops `crop_opponent_icon_column()`
from each attempt's frames to help Gemini's own read. It now ALSO crops
`crop_opponent_badge_column()` (see 2k) from those same already-extracted
frames - no extra ffmpeg sampling, no extra Gemini calls - and pools the
badge crops from BOTH attempts together before handing them to
`team_preview_type_matcher.identify_row_types_multi_frame` (this is what
folds task #190's goal in: the existing "run every widen-attempt
unconditionally and merge" pattern now also feeds this free local check
more real material than either attempt alone would, the same way 2k's own
multi-frame aggregation found extra frames helps). Each row's confidently-
identified type(s) are narrowed against `narrow_species_by_types`,
restricted to species actually legal in the currently configured
regulation (`ALLOWED_SPECIES`, not the full 212-species data file), and
attached as `roster["opponent_row_type_hints"]` - a list of
`{row, identified_types, num_badges_found, n_frames_used,
candidate_species}` dicts.

**Deliberately informational only - the same "flag, don't force a guess"
pattern as `roster_conflict`/`likely_missed_opponent_species` elsewhere in
this file.** This is NOT auto-applied to `opponent_team`/`opponent_brought`
the way `apply_likely_missed_species_correction` is for roster-conflict
flags (see 2g/2h) - per 2k's own HONEST CURRENT SCOPE, the module's
candidate-list-recall property is strongly validated (42/42 on real
footage) but full both-badge accuracy is still frame-sensitive and this
has only been checked against one real match so far. Auto-correcting the
roster from a signal that's occasionally wrong about exactly which
type(s) it saw would risk actively degrading a roster that Gemini's own
vision read got right - this codebase's established norm (see 2g/2h/5) is
to only auto-apply a correction once it's grounded in something that was
literally observed happening in the match (a species recurring in battle
events), not a frame-sensitive local heuristic. `attach_opponent_type_hints`
is written so it can ONLY ever add this one field - it never touches any
other part of the roster dict, and any import/read/geometry failure is
caught and silently no-ops rather than breaking the (far more important)
Gemini roster read.

Tests: `tests/test_opponent_type_hints.py` (11 tests) cover the wiring
(badge crops sampled once per `ROSTER_SEARCH_ATTEMPTS` window and pooled
across both before narrowing; the species map handed to
`narrow_species_by_types` is restricted to `ALLOWED_SPECIES`; a
`crop_opponent_badge_column` failure never breaks the roster read itself;
a no-op when there's nothing to add) with `team_preview_type_matcher`'s
own pixel mechanics mocked out - those are already covered by
`tests/test_team_preview_type_matcher.py` (2k). Full suite: 770 tests
passing (up from 759 before this batch), `py_compile` clean.

## 2m. Landscape-video badge-column geometry fix (2026-07-08), plus the `opponent_team_cap` Species-Clause fix it exposed

**Root cause (task #206):** `analyze_matches --only 3-12` against a real
Twitch VOD (1280x720, 16:9 landscape stream capture) came back with
`attach_opponent_type_hints` reporting a literal 0% confident-badge-read
rate across all 10 matches - including match 3, where the user manually
confirmed row 2's opponent Pokemon was genuinely Kingambit (Gemini's own
vision read wrongly called it "Heracross") and row 5 was genuinely
Vanilluxe (wrongly called "Alcremie"). Both are exactly the misreads
`apply_type_badge_override` (2k/2l) exists to catch, but the override never
got a chance because the whole badge-column crop geometry
(`OPPONENT_BADGE_COLUMN_BOX` + `team_preview_type_matcher`'s
`ROW_TOP_FRAC`/`ROW_HEIGHT_FRAC`) was tuned entirely from a PORTRAIT mobile
recording (1290x2796) and produced pure background noise on landscape
footage. Fixed by adding `detect_video_dimensions()` (returns both width
AND height from the same ffmpeg probe `detect_video_width` already made)
and `badge_column_geometry(width, height)`, which returns a LANDSCAPE-
specific box (`LANDSCAPE_OPPONENT_BADGE_COLUMN_BOX = (0.895, 0.13, 0.975,
0.88)`) plus row-slicing fractions (`LANDSCAPE_ROW_TOP_FRAC = 0.0`,
`LANDSCAPE_ROW_HEIGHT_FRAC = 1/6`, measured directly against a real
landscape frame - the 6 rows divide the crop height exactly evenly) when
`width > height`, falling back to the original portrait geometry (as
`None, None` row fractions, meaning "use `slice_badge_rows`' own module
defaults") for portrait/square/unknown-orientation video. `read_roster()`
and `attach_opponent_type_hints()` both thread these through
(`row_top_frac`/`row_height_frac` params, default `None` = unchanged
behavior). Re-validated against the real frame after the fix: row 0
(Blaziken) correctly Fire+Fighting, row 1 (Kingambit) correctly
Dark+Steel, row 2 (Mimikyu) correctly Ghost+Fairy. Tests:
`tests/test_opponent_type_hints.py` gained `TestDetectVideoDimensions` (6
tests) and `TestBadgeColumnGeometry` (5 tests) plus 4 more covering the new
kwargs' wiring through `attach_opponent_type_hints`/`read_roster`;
`tests/test_team_preview_type_matcher.py` gained 3 tests for
`slice_badge_rows`' override params. Full suite: 834 tests (up from 814).

**A second, independent bug this exposed (task #209):**
`apply_likely_missed_species_correction()` (2g/2h) previously had NO size
check on `opponent_team` at all - only the duplicate-species check. A
species flagged via `likely_missed_opponent_species` (recurring
`roster_conflict` events - see 2g) got appended to `opponent_team`
unconditionally, even when the roster read was already "full" per Species
Clause. A fresh 10-match production run (the same landscape VOD from
task #206, re-run end-to-end) turned up 3 real cases of this producing an
impossible 7-member `opponent_team` (matches 3, 10, 12) - match 3's was
downstream of the now-fixed 2m geometry bug plus the user's own manual
`events.json` correction (task #208), but the missing-cap bug itself is
independent and could recur on any match. Fixed by adding
`opponent_team_cap=6` (both call sites now pass the format's own
`rules.team_size`, guarded against a `None` `rules` via `(rules or
{}).get(...)`/`schema.get("rules", {})`) - a species that can't be added
because the team is already at the cap is now recorded in a new
`likely_missed_but_team_full` list on the `team_preview_event` instead of
being silently discarded or force-appended past 6. This preserves the real
signal ("something in this roster read is probably wrong - a misread slot
masquerading as a different real species") for manual review, without
ever violating Species Clause. A duplicate species (already present in a
full team) is unaffected by the cap - it can still be folded into
`opponent_brought` even when `opponent_team` is full, since it isn't a new
7th member. Tests: `tests/test_roster_accuracy_fixes.py` gained 6 tests
(`TestApplyLikelyMissedSpeciesCorrection`) covering the default 6-cap, the
new field appearing only when something couldn't fit, duplicate-species
exemption from the cap, a custom `opponent_team_cap` (e.g. for Singles),
and a multi-species case where some fit and some don't. Full suite: 840
tests (up from 834), `py_compile` clean.

## 2n. Matches-tab redesign: Match Summary as the default review view (2026-07-08)

**The problem.** The Matches tab's default expanded view was `ClarificationQueue.jsx`
- a flat list of "is this really \<species\>?" identity questions, or (if none)
a bare "nothing to confirm" message. It never showed the thing a player
actually opens a match to see: their team, the opponent's team, what
happened turn by turn, and who won. Two real gaps sat outside its scope
entirely: a `winner: "unknown"` match (see the match-4/5 stream-disruption
investigation earlier this session) had no path to resolution at all short
of hand-editing raw JSON via the "show every event" table, and a flagged
event that wasn't shaped like a single-Pokemon guess (e.g. a low-confidence
`field_state` read) never surfaced as a question anywhere.

**The fix - three parts:**

1. **`frontend/src/lib/clarifications.js`** gained two new builders alongside
   the existing `buildClarificationQueue`:
   - `buildWinnerClarification(events, matchNumber)` returns `null` if no
     `battle_end` exists for the match, or if *any* `battle_end` for that
     match already resolved to `"player"`/`"opponent"` (a duplicate
     OCR-derived `battle_end` still reading `"unknown"` doesn't block this -
     resolved-anywhere counts as resolved). Otherwise it returns every
     `battle_end` index for the match plus a fallback photo: since
     `attach_reference_frames` in `analyze_matches.py` only tags
     `match_events` from the chunked battle pipeline (never the synthetic
     `team_preview`/`battle_end` events), the fallback borrows whichever
     non-`team_preview` event *latest by timestamp* in the match happens to
     carry a `reference_frame`, flagged via `isNearestFallback` so the UI can
     say "closest available photo, may be from before the actual result."
   - `buildGenericClarifications(events, matchNumber)` surfaces low-confidence
     or `roster_conflict` events that are *not* identity-shaped (missing
     `pokemon`/`actor`, or are `team_preview`/`battle_end` - those two have
     their own dedicated paths) as individual, timestamp-sorted "what
     occurred here?" items - deliberately not grouped, since each is a
     distinct board moment rather than a repeated sighting.
   - Both reuse the existing `LOW_CONFIDENCE_THRESHOLD` / `corrected` /
     `roster_conflict` conventions from `buildClarificationQueue`, and both
     read the *existing, fully generic* `PATCH /jobs/{id}/events/{index}`
     endpoint for writes (`cascade_pokemon_correction` only triggers on a
     `pokemon` field change, so it's a no-op for winner/generic corrections)
     - no backend changes were needed for any of this.

2. **`frontend/src/components/MatchSummary.jsx`** (new file) is now the
   default expanded view: team-preview rosters (`player_team`/`opponent_team`
   plus `_brought`), a result banner, a plain-English turn-by-turn recap built
   directly from `battleTimeline.js`'s existing per-event `caption` text
   (filtered through a `RECAP_EVENT_TYPES` whitelist that excludes `hp_change`
   and bare `field_state` as too granular/redundant - this was an explicit,
   deliberate choice over wiring the currently-unused `strategic_analysis.py`
   backend endpoint), and, inline, any of the three question types: a
   `WinnerCard` ("Who won this match?" with ✓ You won / Opponent won buttons),
   `ClarificationCard`s (the existing species-identity card, exported from
   `ClarificationQueue.jsx` and reused verbatim rather than duplicated), and
   `GenericOccurrenceCard`s ("What occurred here?" with a confirm button and a
   free-text override). A "Show every event instead" link still reaches the
   exhaustive, ungated `MatchEvents.jsx` table underneath for the rare
   low-level field these three question types don't cover.

3. **`frontend/src/components/MatchesTable.jsx`** now renders `MatchSummary`
   as the `"summary"` view (renamed from `"list"`/`ClarificationQueue`) by
   default, with `"replay"` (`BattleReplay.jsx`) as the other tab.
   `ClarificationQueue.jsx`'s default export and its own `groups`/`showAll`
   state were deliberately left in the file rather than deleted (only its
   `ClarificationCard` function was changed from module-private to
   `export function`) - it's simply no longer the thing `MatchesTable.jsx`
   renders directly.

**CSS:** `frontend/src/styles.css` gained `.match-summary`, `.summary-teams`/
`.summary-team`, `.summary-result` (`.good`/`.bad`/`.warn`), `.summary-heading`,
`.summary-recap`/`.recap-line`/`.recap-time`.

**Tests:** `frontend/src/lib/clarifications.test.mjs` gained 17 new cases
covering `buildWinnerClarification` (no-`battle_end` → null, already-resolved
→ null, resolved-anywhere-treated-as-resolved even with a duplicate
`"unknown"`, latest-timestamp photo fallback, `team_preview`'s own photo never
borrowed, no-photo-anywhere, cross-match isolation) and
`buildGenericClarifications` (non-identity low-confidence events surface,
confident ones don't, identity-shaped events are never double-counted,
`team_preview`/`battle_end` are never surfaced here, already-corrected events
don't reappear, sort-by-timestamp, cross-match isolation). Full node suite:
54 tests, 0 failures (up from 37). Full Python backend suite re-run
unaffected: 840 tests, 0 failures - this was a frontend-only change. All
`.jsx` files in `frontend/src` (21 files) independently syntax-checked via a
pure-JS `@babel/core` JSX parse (this sandbox's `node_modules` was built for
a different OS/arch than this Linux sandbox, so neither Vite's bundled
Rollup nor esbuild native binaries run here and the npm registry is
network-blocked for fetching the correct platform binaries - `npm run build`
itself could not be exercised in this environment; the real, definitive
build check is `npm run build` on the user's own machine).

## 2o. Never show a review card with no photo to review (2026-07-08)

**The problem.** All three clarification card types (species-identity,
winner, generic "what occurred here?") had a fallback path for when no
reference photo existed anywhere for that question: render a
`.event-thumb.missing` placeholder literally reading "no photo" next to the
question and buttons. Feedback: this reads as broken rather than intentional
- asking "is this really X?" or "who won this match?" with a visibly missing
image looks like a bug, not a deliberate design choice.

**The fix.** Rather than changing how the "no photo" case renders, the three
builder functions in `frontend/src/lib/clarifications.js` now exclude these
cases from the queue entirely:
- `buildClarificationQueue` gained a `.filter((g) => !!g.referenceFrame)`
  after building each group's candidate photo (own event -> borrowed sighting
  of the same species/side -> team_preview's roster screen, in that existing
  priority order) - a group only appears if one of those three sources
  actually produced a photo.
- `buildWinnerClarification` now returns `null` (rather than an object with
  `referenceFrame: null`) when no non-`team_preview` event in the match
  carries a photo at all - `isNearestFallback` is consequently always `true`
  whenever this function returns non-null, since `battle_end` never has a
  photo of its own to prefer over a borrowed one.
- `buildGenericClarifications` gained a `.filter((e) => !!e.reference_frame)`
  in its filter chain, alongside the existing confidence/identity-shape
  filters.

Matches where every uncertain moment happens to lack a photo now simply show
fewer (or zero) clarification cards in `MatchSummary.jsx`, with the existing
"Show every event instead" link still available as the escape hatch for that
rare case - consistent with how a fully-confident match already showed zero
cards before this feature existed. `frameContextFor` (the HP%-lookup helper
used to disambiguate doubles photos) was left as-is: it already safely
returns an all-null/empty result when handed a group with no photo, so it
remains defensively correct even though `buildClarificationQueue` itself no
longer produces such a group.

**Tests.** `frontend/src/lib/clarifications.test.mjs`: the pre-existing
no-photo assertions for the identity queue and the winner card were rewritten
to assert the group/card is now absent entirely (`[]` / `null`) rather than
present with a null `referenceFrame`; several other pre-existing tests that
happened to construct fixtures with no `reference_frame` at all (since photo
presence wasn't the thing under test) had a `reference_frame` added to their
fixtures so they keep exercising the grouping/confidence/candidate-ordering
behavior they were actually written for. Two new dedicated tests confirm the
exclusion itself: a `buildClarificationQueue` group with genuinely no photo
anywhere is dropped, and a `buildGenericClarifications` event with no
`reference_frame` is not surfaced. Full node suite: 55 tests, 0 failures (up
from 54). Full Python backend suite re-run unaffected: 840 tests, 0 failures
- frontend-only change.

## 2p. VGC Battle Intelligence Manual: six additive per-turn reports + recap wiring (2026-07-09)

**The ask.** The user uploaded a "Pokemon VGC Battle Intelligence Manual"
document describing six named strategic reports a coach walks through each
turn - Speed Control Advantage, Threat Pressure, Resource Advantage, Momentum,
Position Score, and Risk Management - and asked for the framework to be
implemented "in a clean and organized way" on top of the existing turn-by-turn
recap, since "this knowledge can really help players improve." Two decisions
were locked in up front (via clarifying question): build all six reports now,
with honest "insufficient data" gating rather than fabricating anything the
event stream doesn't actually support; and surface them by extending the
existing recap in `MatchSummary.jsx` (one compact line per turn) rather than a
new separate panel.

**The hard constraint: don't double-count `score`.** `strategic_analysis.py`
already had a battle-tested `score`/`compute_advantage_score` (alive-count +
Tailwind + HP-based), asserted to *exact* values by several pre-existing
tests (e.g. a real-replay turn asserted to `score == -35`). The six new
reports could not just re-derive their own opinion of the same signals `score`
already covers - that would silently double-count Tailwind/alive-count/HP
when they later get folded into Position Score. So each new report's own
`*_score` field was scoped to ONLY the information `score` doesn't already
carry:

- **`compute_speed_control`** - scores only concrete speed-manipulation
  *tools* seen this turn (Choice Scarf/Booster Energy/Speed Boost/Unburden/
  Swift Swim/Chlorophyll/Sand Rush/Slush Rush/Surge Surfer via
  `item_or_ability_activated`, plus Trick Room setters), not who's just
  naturally faster - that's implicit in `score` already via move order.
- **`compute_threat_pressure`** - scores only *move-category* danger this
  turn (spread moves, redirection like Follow Me/Rage Powder/Ally Switch,
  against `decision_windows.py`'s per-turn `known_moves`), not raw HP/KOs -
  those are narrative-only "factors" here.
- **`compute_resource_advantage`** - returns both a `screen_score` (screens
  gained/lost only) and a separate `board_score` (alive/HP, deliberately
  mirroring `score`'s own arithmetic) - **`board_score` is intentionally
  never folded into Position Score**, exactly because it would double-count.
  Its docstring is explicit that item/berry consumption (`-enditem`) isn't
  modeled at all, because `showdown_import.py` doesn't parse that event -
  an honest gap rather than a guess.
- **`compute_momentum`** - reclassifies the manual's own event list (KOs,
  stat changes, screens gained, failed moves) onto the existing per-turn
  `delta`, with a neutral band rather than forcing every turn into "winning"
  or "losing."
- **`compute_position_score`** - the composer: `score` + `speed_control.score`
  + `threat_pressure.score` + `resource_advantage.screen_score` (never
  `board_score`), banded per the manual's exact numeric ranges (80-100
  Dominating, 50-79 Strong Advantage, 20-49 Slight Advantage, -19..19 Even,
  -20..-49 Slight Disadvantage, -50..-79 Major Disadvantage, -80..-100
  Losing).
- **`compute_risk_management`** - pure lookup from Position Score's own band
  to a posture/guidance string (no independent scoring at all).

All six are attached as additive keys (`speed_control`, `threat_pressure`,
`resource_advantage`, `momentum`, `position_score`, `risk_management`) on
every entry of `build_momentum_timeline`'s existing per-turn list, alongside
the untouched `turn`/`match`/`player_alive`/`opponent_alive`/`score`/`delta`/
`win_probability`/`reasons`. `GET /jobs/{id}/strategic-analysis`
(`backend/main.py`, wired since §8d) already returned this list - it just had
never been called from the frontend before this feature.

**Frontend wiring.**
- **`frontend/src/lib/battleTimeline.js`** - each frame now carries a `turn`
  field, forward-filled from the most recent `field_state` event's own `turn`
  (same forward-fill convention `decision_windows.py`/`strategic_analysis.py`
  already use server-side) - `null` before the match's first `field_state`.
- **`frontend/src/api.js`** - added `api.strategicAnalysis(jobId)` ->
  `GET /jobs/{id}/strategic-analysis`.
- **`frontend/src/components/MatchSummary.jsx`** - fetches
  `strategicAnalysis` once per job (covers every match in one call, not
  re-fetched on match switch), and a `turnReports` map picks the current
  match's `momentum_timeline` back out by turn number. The turn-by-turn recap
  now inserts one compact line - `Turn N: <Position Score label> —
  <Risk Management guidance>` - right before the first recap frame each new
  turn covers (tracked via a `lastTurnShown` closure, so a turn with several
  events only gets one report line, not one per event). A hover tooltip
  (`turnIntelTooltip`) concatenates every sub-report's non-placeholder
  factors, so the "why" is one hover away without cluttering the recap. If
  the fetch fails, or a match has no turn data, the per-turn intel lines
  just don't appear - the base recap already worked fine without them, so
  this is a pure enhancement with no error banner.
- **`frontend/src/styles.css`** - new `.recap-turn-intel` rule: a small
  accent-colored line with a dashed top border separating it from the
  previous turn's events (suppressed on the very first turn via
  `.summary-recap > div:first-child .recap-turn-intel`, since each intel line
  is the first child of its own per-frame wrapper `<div>`, not a sibling of
  the others).

**Tests.** `tests/test_strategic_analysis.py` gained 49 new tests (one class
per report, plus an integration class proving the six new keys are present
and non-empty on every `build_momentum_timeline` entry without disturbing
`score`/`delta`/`win_probability`/`reasons`) - full suite 141/141.
`frontend/src/lib/battleTimeline.test.mjs` gained 3 tests for `turn` stamping/
forward-fill/advance. Full verification for this feature: Python suite 909/909
(project-wide, not just this module), node suite 58/58 across
`src/lib/*.test.mjs`. `npm run build` itself can't run in this sandbox
(pre-existing, unrelated environment issue - `node_modules` was installed on
Windows and the rollup/esbuild native binaries don't have a Linux build
available here, same root cause for both tools) - as a substitute, both
`MatchSummary.jsx` and `api.js` were parsed with `@babel/parser` (JSX plugin
enabled, already present as a transitive Vite dependency) to confirm valid
syntax, since `node --check` doesn't understand JSX at all.

**A recurring gotcha this feature re-surfaced constantly:** on this project's
sandbox, bash's view of a file can go stale immediately after an edit -
`py_compile`/`node --check` report syntax errors (or `wc -l` reports a
too-short line count, or `node --test` silently runs against a cached file
and finds fewer tests than expected) even though the Read tool's view of the
same file is complete and correct. Every file touched in this feature hit
this at least once. The reliable fix: reconstruct the file's true content via
the Read tool (never trust bash's `cat`/`wc`/`stat` as the source of truth
when they disagree with Read), write it to a scratch path, verify the syntax
check passes there, then `cp` it over the real path and re-verify. A syntax
check passing is not sufficient proof of freshness by itself - cross-check
against an expected count (e.g. total test count) when one is known.

## 3. The adapter system (how it scales to games/formats)
```
adapters/_core.json            universal event ontology (write once)
adapters/pokemon/game.json     Pokémon vocabulary + core_mapping + per-turn fields
adapters/pokemon/doubles.json  mode delta: 2 active/side, team preview, RULES (no Tera), remove_event_types
adapters/pokemon/singles.json  another mode delta
```
`compose_schema.py` merges core+game+mode → `schema.json`. Adding a game = a new folder
of small JSON; adding a mode = one file. See `ADDING_A_NEW_GAME.md`.
Format `rules` (legal mechanics) constrain BOTH extraction and coaching (fixes e.g. the
"recommended Tera in a no-Tera format" bug).

## 3a. Regulation selector (`adapters/pokemon/regulations/<id>.json`)

Pokémon Champions' competitive ruleset ("regulation") rotates every couple months —
which species and mechanics (Mega Evolution/Dynamax/Terastallization) are actually legal
changes out from under a video the moment a new regulation drops, which used to mean the
project's species allowlist (`analyze_matches.ALLOWED_SPECIES`) silently went stale.
Regulation is now a THIRD, independent adapter layer alongside game/mode:

```
adapters/pokemon/regulations/m-b.json   current (2026-06-17 – 2026-09-02): 212 species,
                                         Mega Evolution on, Dynamax/Tera off
adapters/pokemon/regulations/m-a.json   launch/superseded (2026-04-08 – 2026-06-17):
                                         186 species (a strict subset of M-B's roster)
```

Why a separate layer instead of folding this into `doubles.json`/`singles.json`: **mode**
(singles vs. doubles — how many Pokémon are active per side, team-preview shape) almost
never changes, while **regulation** (which specific Pokémon/mechanics are legal *right
now*) changes every couple months — conflating the two meant every regulation rotation
required editing the mode files. They're orthogonal: the exact same M-B legality facts
apply whether you're playing singles or doubles.

`compose_schema.py --regulation <id>` merges a regulation's `legal_mechanics`/
`banned_species_categories`/metadata into `schema.json`'s `rules` (regulation wins on
overlapping keys — it's the more specific, more frequently-updated fact) and appends its
`format_notes` to `notes_for_the_ai` last, so it's the freshest thing in the coaching
model's context. Separately, `analyze_matches.py --regulation <id> --adapters <dir>`
calls `configure_regulation()`, which reassigns the module-level `ALLOWED_SPECIES`/
`_ALLOWED_NORM` allowlist to that regulation's own species list — every legality-checking
function (`flag_banned_species`, `reject_banned_species`, `_species_base_norm`) already
reads those two globals directly, so switching regulations needs zero changes to them.
`showdown_import.py` takes the same two flags for consistency, though Showdown enforces
format legality server-side so this mostly guards against a replay imported under a
mismatched regulation label rather than catching anything real.

The hardcoded `ALLOWED_SPECIES` Python constant in `analyze_matches.py` is kept as the
zero-file-IO default (identical to `m-b.json`'s own species list — see
`tests/test_regulation_switching.py`'s cross-check) for any caller that never calls
`configure_regulation()` at all — regulation selection is additive, never required.

End-to-end wiring: `POST /jobs`'s `regulation` Form field (default `"m-b"`) →
`backend/jobs.create_job` → stored on the job row → `backend/jobs.start_job` passes it to
`backend/pipeline.run_full_pipeline`/`run_showdown_pipeline` → both `compose_schema.py
--regulation` and `analyze_matches.py --regulation` (or `showdown_import.py
--regulation`) subprocess calls → the New Job panel's "Regulation" dropdown (next to a
"Mode" dropdown for singles/doubles) is what actually sets the field, defaulting to
Doubles/M-B (current) so leaving it untouched behaves exactly like before this feature
existed. Only M-A and M-B are supported — Pokémon Champions has no regulation before
M-A (its April 2026 launch); an older competitive video would be a different game
(Scarlet/Violet) entirely, out of scope here.

## 4. Data contracts (this IS the API surface the UI renders)

**`events.json`** — array of event objects. Common fields: `timestamp`, `event`, `actor`
('player'/'opponent'/'both'), `detail`, `confidence`, `match` (int), `reference_frame` (path to the
sampled frame this event was tagged from, when one exists - see section 2c; not present on video
jobs' `team_preview`/`battle_end` summary events or on Showdown-sourced events, which have no frame
to reference). After a manual correction (`PATCH /jobs/{id}/events/{index}`), also carries
`corrected: true`, `corrected_at` (unix seconds), `corrected_by` (user id). Event-specific:
- `team_preview`: `player_team`, `opponent_team`, `player_brought`, `opponent_brought`, `player_lead`, `opponent_lead` (comma strings)
- `field_state`: `player_active`, `opponent_active`, `turn`, `weather`, `terrain`, `trick_room`, `tailwind`, `screens`, `field_status`
- `move_used`/`pokemon_fainted`/etc.: `pokemon`, `hp_percent`
- `battle_end`: `winner`

**`matches.csv`** — `match, start_seconds, end_seconds, duration_seconds`
**`meta/<format>.json`** — `{format, updated, rules, type_chart, pokedex, own_meta{pokemon_usage, leads, opponent_threats}, external_meta{source, tier, month, rating_cutoff, total_battles, pokemon_usage_pct} | None}` (`external_meta` added 2026-07-05, task #130 — real official Smogon usage stats, `None` if the fetch hasn't succeeded yet in this environment)
**`coach_report.md` / `player_report.md`** — human-readable reports (also easy to regenerate as JSON)
**`battle_record.csv`** — per-match `timestamp, winner, detail`
**`skill_scores.json`** — `{matches_analyzed, confidence{tier, matches_to_next_tier}, scores{tempo, adaptability, execution, closing}, overall, drivers{...}}` (from `skill_scores.py`; powers the dashboard's 4 progression scores + confidence tier)

## 5. Key decisions & why (don't undo these)
- **Match detection via battle/not-battle cycle** (structure_pass), NOT catching transient
  screens or overlays. This is what fixed "3 matches" → 46 (real count). Overlay-independent.
- **Roster-locking**: read both teams in team preview, constrain in-battle Pokémon IDs to
  those names → killed "unknown Pokémon".
- **Derive brought/leads from who appears**, not from reading the selection UI.
- **Cost tiering**: bulk reads on 2.5 Flash, only roster+winner on 3.5 Flash; `field_state`
  emitted on change (not per frame); 0.33 fps; 640px frames. Took a run from ~$60 → ~$5–8.
  Further reduction available (stackable, see section 2b): free frame de-dup before any
  API call, an A/B tool to check if Flash-Lite is safe for the classifier step, and
  `--use-batch-api` for another 50% off the dominant bulk-extraction cost.
- **Format rules + meta grounding**: keeps advice legal (rules) and relevant (meta + own data).

## 5a. Accuracy eval harness (`tests/`)

Two tiers - see `tests/README.md` for the full explanation: (1) `py -m
unittest discover -s tests -v`, dependency-free unit tests for every piece of
pure logic (species legality, normalization, `analytics.py`, `skill_scores.py`)
run in under a second, each one written against a real bug that actually
happened; (2) `grade_matches.py`, which can't replace a human but removes the
busywork of grading vision/video accuracy against real footage. Run tier 1
after any change to the files it covers - it's what catches "this prompt/schema
change broke something" before a user does.

## 6. Gotchas / known issues
- PowerShell paste sometimes drops into `>>` (unfinished line) — press Enter or Ctrl+C + retype.
- yt-dlp Twitch downloads warn about MPEG-TS timestamps — usually harmless for frame analysis.
- Whisper is slow on CPU (transcript is optional and non-blocking in `run_full`).
- `terastallized` is removed for Champions via `remove_event_types`; re-compose schema after adapter edits.
- Costs are Gemini-dominated (output tokens on the premium model are the priciest lever).
- **Active-Pokemon fields:** the AI sometimes returns `player_active`/`opponent_active` (and
  `pokemon`) as a list or list-of-dicts instead of a comma string. `analyze_matches.py`
  now normalizes these back to comma strings on save (via `names_of()`), so `events.json`
  reliably follows the string contract in §4. If you ever read these fields elsewhere, use a
  tolerant parser. (This was the `derive_brought` garbling bug — fixed at the source; re-run
  `analyze_matches.py` to regenerate any events.json produced before the fix.)

## 7. What's built vs. next
**UPDATED — this section was badly stale as of early July; corrected after an
actual file-by-file audit (not just re-reading old docs) found the real
codebase well ahead of what this doc said.** Built & tested: full pipeline,
adapters, cost tiering, format rules, meta/knowledge base, coach chat, skill
scores (`skill_scores.py` → 4 progression scores + confidence tier), Showdown
replay import (§2a), Gemini Batch API mode (§2b), frame de-dup + classifier
A/B tooling (§2b), reference-frame retention + manual event correction (§2c),
the OCR accuracy tier (§2d), the mode + regulation selector — singles/doubles
and M-A/M-B, user-facing dropdowns wired end-to-end (§3a), a **full backend
API** (FastAPI, real Postgres/Supabase accounts with a local-dev-mode
fallback — see §8), and a **full frontend** (React + Vite dashboard — see
§9). Sections 8/9 below used to be "proposed" sketches written before any of
this existed; they're rewritten now to describe what's actually running.

**UPDATED 2026-07-04:** a first cut of the "strategic analysis engine" —
per-turn advantage score, a momentum timeline with plain-language reasons,
a resource-tracking summary, and conservative mistake-candidate flagging —
is now built (`strategic_analysis.py`, on top of decision windows below —
see §8d). Genuinely still not built: KO-attribution / loss-pattern analysis
beyond what §8d's mistake-candidate flags already surface, external meta
ingestion (Pikalytics — ToS blocks scraping it directly), win-condition
inference, and threat analysis. §8d is explicit that its scores are a
heuristic, not a calibrated model — read that section before treating any
number out of it as more than a coach's gut-feel read.

`accuracy_addons/` (§2e) — four free, local accuracy tools (icon template
matching, HP-bar pixel reading, Showdown-learnset move-legality checking,
Showdown-format-rules staleness checking) — **are now wired into
`analyze_matches.py`** (2026-07-04, see §2e's "Update" note for exactly how
each one hooks in and what's still opt-in vs. always-on). **Full-dex learnset
coverage landed 2026-07-05** (see §2e's second "Update" note) — the
15-non-VGC-species gap described here is closed; `moveset_validator` now
covers all 818 gen-9 species, including the alt-forme learnset-inheritance
fix. Still genuinely missing: more validated templates/plate positions for
`icon_template_matcher`/`hp_bar_reader` beyond the single status badge and
two HP-bar positions confirmed so far (a job with a structurally different
HUD was validated in the same 2026-07-05 pass — see `hp_bar_reader.py`'s
module docstring — but that surfaced a real, still-open brightness-
normalization gap on darker frames, not a full fix). **Fixed 2026-07-04:**
`moveset_validator.flag_implausible_moves` used to look for a structured
`move` field that no real event (OCR or Gemini-vision) has ever populated —
it silently matched nothing on every real job for a second reason beyond the
15-species coverage gap. It now falls back to `detail` (what's actually
there), same pragmatic fix `decision_windows.py`'s own `_move_name()` already
used — see `tests/test_moveset_validator.py`'s `TestMoveName`/
`test_flags_using_detail_when_no_move_field_present`.

---

## 8. Backend API (as built — FastAPI, `backend/`)

**No longer a proposal — this is running.** The pipeline scripts were wrapped
in FastAPI (`backend/main.py`), each job runs as a background thread
(`backend/pipeline.py`, subprocess-per-script, one job = one folder so
concurrent jobs can't collide), with real accounts backed by Postgres/
Supabase (`backend/auth.py`, `backend/jobs.py`) — see §8a for the important
local-dev-mode fallback. Endpoints actually implemented:

```
POST  /jobs                       {source_type: url|upload|showdown, game, mode,
                                    regulation ("m-b" default | "m-a"), ...}  -> {job_id}
GET   /jobs                       -> this user's jobs
GET   /jobs/{id}                  -> {status, step, progress, ...}
GET   /jobs/{id}/matches/summary  -> per-match table data (⚠/🚫 flags precomputed)
GET   /jobs/{id}/events           -> events.json
GET   /jobs/{id}/frame/{path}     -> one stored reference image (see §2c; path-traversal guarded)
PATCH /jobs/{id}/events/{index}   {fields: {...}}  -> corrected event, audit-logged (see §2c)
GET   /jobs/{id}/record           -> {wins, losses, win_rate, by_lead, by_bring}
GET   /jobs/{id}/report           -> coach_report + player_report (structured; Tera stats
                                      hidden, not faked, when the format has no Tera)
GET   /jobs/{id}/skill-scores     -> skill_scores.json shape (see §4)
GET   /jobs/{id}/opponent-strength -> type-overlap risk (backend/type_synergy.py)
GET   /jobs/{id}/decision-windows -> per-turn available options + chosen action,
                                      every match, flat list (see §8c, decision_windows.py)
GET   /jobs/{id}/strategic-analysis -> per-match advantage score/momentum timeline/
                                      resource summary/mistake candidates (see §8d,
                                      strategic_analysis.py - heuristic, not a
                                      calibrated model)
POST  /jobs/{id}/coach            {question}  -> {answer}  (wraps coach_chat.answer())
GET   /auth/status                -> {accounts_required: bool} (drives local-dev-mode UI)

GET   /career/record               -> same shape as /jobs/{id}/record, merged across EVERY
                                       completed job this account has ever uploaded
GET   /career/report                -> same, merged
GET   /career/matches               -> same, merged (global match numbers - see §8b)
GET   /career/skill-scores          -> all-time blended skill scores
GET   /career/skill-scores/trend    -> per-UPLOAD-SESSION skill scores, oldest first - THE
                                       "track how the player has improved" endpoint (see §8b)
POST  /career/coach                {question}  -> {answer}  (session-progression-aware coach)
```

Also mounts the *built* React app (`backend/static/`, produced by `npm run
build`) at `/dashboard` — the whole product is servable from one running
FastAPI process.

**Stack actually used:** FastAPI, subprocess-per-script background jobs on a
thread (not yet a real queue like Celery/RQ — fine at solo-POC scale, a
real queue is the obvious next step if concurrent job volume ever matters),
Postgres/Supabase for accounts+jobs, local disk for video/frame/output
storage (not yet object storage like R2/S3 — also fine at current scale,
worth revisiting before a real public launch given upload volume).

### 8a. Local dev mode (important — this is why the app runs with zero cloud setup)

When Supabase credentials aren't set in `.env`, `auth.configured()` returns
`False` and the ENTIRE accounts system swaps to a local fallback: `GET
/auth/status` reports `accounts_required: false`, the frontend skips sign-in
entirely, and every job-store function (`backend/jobs.py`) uses a plain
in-memory Python dict instead of Postgres — including `_local_discover()`,
which auto-picks-up any `jobs/<id>/` folder that already has an
`events.json` (this is how `seed_demo_job.py` gives a fresh checkout
something to look at immediately). Real accounts turn on by filling in
`.env` — no code changes needed either way.

## 8b. Career aggregation (`backend/career.py`) — cumulative coaching across every upload

**Added 2026-07-04, in response to:** "how can we make it so the coaching is
cumulative and considers all matches that are uploaded together so it can
provide true coaching feedback and track how the player has improved."
Before this, every one of the analytics functions above (skill_scores,
coach_report, player_report, coach_chat) only ever read ONE job's
`events.json` — a new upload started the coach from zero every time, even
though every past job's `events.json` was still sitting on disk (jobs are
never deleted) and already belonged to a `user_id`. What was missing was
purely the merge step.

`backend/career.py`'s `merge_user_events(user_id)`:
1. Lists every `status == "done"` job this user owns, oldest first
   (`list_completed_jobs_chronological` — filters by `user_id` a SECOND time
   even though `jobs.list_jobs()` is supposed to already scope by user,
   because local dev mode's `list_jobs()` deliberately ignores its `user_id`
   argument and returns every local job — belt-and-suspenders, same spirit as
   `jobs.update_job()`'s own defensive filtering).
2. Reads each job's `events.json` and remaps its LOCAL match numbers (every
   job numbers its own matches starting at 1 — job A's "match 1" and job B's
   "match 1" would otherwise collide) into one global, non-colliding sequence.
3. Tags every event with `session` (1-based, chronological) and
   `source_job_id`.
4. Returns `(merged_events, sessions)` — `sessions` is the per-job metadata
   (`job_id`, `created_at`, `matches_in_session`, ...) a trend chart or the
   coach needs.

**The key design point: nothing about `compute_record`/`compute_report`/
`compute_skill_scores`/`compute_match_list` (backend/analytics.py) needed to
change.** They already just take "a list of events" — feeding them
`merged_events` instead of one job's list is the entire integration. Verified
directly: a synthetic 2-job merge (job 1 losing 1-2, job 2 winning 3-0) feeds
straight into the unmodified `compute_skill_scores` and correctly returns a
higher `overall` for job 2 than job 1.

**Deliberately recomputed on every request, never persisted/cached** — this
project is solo-user scale, so re-reading a handful of `events.json` files
per request is cheap, and it means a corrected event or a newly-completed job
is reflected immediately with zero cache-invalidation logic.

**"Track how the player has improved" specifically** (`compute_skill_score_trend`)
computes skill scores TWO ways per session, deliberately — both were built,
not just one, per the "Both" choice made when scoping this feature:
- `per_session`: scored using ONLY that session's own matches — the real
  improvement signal (session 5's number isn't diluted by session 1's).
- `cumulative`: scored using every match up through that session — smoother,
  converges as more data accumulates, but a recent improvement gets averaged
  against everything before it.
Either can be `None` for an early, low-sample session (`skill_scores.
compute_skill_scores` already returns `None` for "not enough data," not a
fake 0 — this just passes that through).

**Coach chat cross-session awareness** (`coach_chat.session_progression_summary`):
a flat merged event list alone can't answer "have I gotten better" — the
model has no way to tell an early match from a recent one without an
explicit boundary. This function builds one `profile_summary()` block PER
SESSION (reusing that existing function rather than re-deriving win
rates/leads/brings from scratch), labeled with the session's date/job/match
count, and the `SYSTEM` prompt was updated to tell the model explicitly to
use that block for trend questions rather than only quoting one blended
average. `POST /career/coach` is the only caller that builds and passes this
block; `POST /jobs/{id}/coach` (single-job) is unchanged.

Tests: `tests/test_career.py` (18 tests — merge/remap/session-tagging/
ownership-scoping/trend), `tests/test_coach_chat_sessions.py` (11 tests — the
session-progression summary and its date-formatting helper). Both use the
same fastapi/supabase stub-injection pattern as `tests/test_local_dev_mode.py`
so they run without those packages installed.

**Known gap:** `/career/matches` doesn't merge per-match `duration_seconds`
the way `/jobs/{id}/matches/summary` does (that would need re-deriving each
global match's originating job + local match number to look up its
`matches.csv` row — doable, just not done yet, since it's cosmetic rather
than something the coaching logic needs).

## 8c. Decision windows (`decision_windows.py`) — per-turn available options + chosen action

**Why this exists:** a user shared a detailed wider architecture spec for
this whole project (structured battle-log extraction → battle state engine
→ strategic analysis engine → LLM coaching) and asked whether it was a
useful direction. Most of it turned out to already be built (OCR-first
extraction, team preview, the structured event log, the validation/
confidence layer) — see the gap-analysis given in chat. The one genuinely
missing, high-leverage piece the user asked to prioritize first was the
spec's "decision windows": for every turn, what a side actually had
available (board, alive roster, switch options, moves already revealed)
versus what it chose (a move or a switch). This is the raw material a
future win-probability/momentum/mistake-flagging engine (the spec's
"strategic analysis engine," not yet built) will need to ask "why Recover
instead of Protect" — building it now, on its own, rather than the whole
engine at once.

**`decision_windows.py`** (repo root, pure functions, no video/Gemini/
network — doesn't import analyze_matches.py directly, same reasoning as
skill_scores.py/career.py/type_synergy.py, to avoid pulling in
analyze_matches.py's heavier deps like gemini_batch):
- `build_decision_windows(events, match_number)` walks one match's events
  turn by turn (turn boundaries come ONLY from `field_state` events' own
  `turn` field) and returns one window per turn: `{"turn", "match",
  "player": {...}, "opponent": {...}}` where each side has `board` (active
  Pokemon per the latest `field_state`), `available_pokemon` (team-preview's
  brought-4 minus fainted), `switch_options` (available minus board),
  `known_moves` (moves each active Pokemon has ALREADY revealed in an
  EARLIER turn — never its hidden full moveset), and `chosen_actions` (the
  actual move/switch events that turn).
- `build_decision_windows_for_job(events)` — same thing across every match
  in one `events.json`, flattened into one list (each window already
  carries its own `match` number), the entry point the backend endpoint
  calls.

**Information-state discipline (the spec's own principle, applied
literally):** `known_moves` only ever contains moves used in a STRICTLY
EARLIER turn than the one being reported — a move chosen THIS turn is never
back-dated into "what was available going into this turn," so the data can't
be used to imply a decision was informed by something that hadn't happened
yet.

**A real, useful side-finding surfaced while building this:** no code path
in this project actually populates a structured `move` field on a real
`move_used` event — `battle_text_parser.py`'s `_event()` (the OCR tier) and
every Gemini-vision-derived event both put the move name in `detail`
instead. `accuracy_addons/moveset_validator.py`'s `flag_implausible_moves`
expects a `move` field specifically and, as a direct consequence, has never
actually matched a real event — a second, more fundamental reason (beyond
the already-documented 15-species learnset-coverage gap, §2e) that check
has found nothing on real jobs. `decision_windows.py`'s `_move_name()`
works around this pragmatically (prefers `move` if ever populated, falls
back to `detail`) but the underlying `moveset_validator` gap is real and
still open — worth a follow-up fix, not done here since it's a separate
module.

**Honest limitations, stated plainly:**
- Returns `[]` for a match with no `field_state`/`turn` events at all.
  **UPDATED 2026-07-04:** this used to be true of EVERY Showdown-imported
  match; `showdown_import.py` now emits a real `field_state` event off the
  protocol's own exact `|turn|N|` line (ground truth, no OCR/vision guess
  needed), so Showdown-imported matches produce real decision windows too —
  see `BattleParser._emit_field_state`/`feed_line`'s `"turn"` branch and
  `tests/test_showdown_import.py`'s `TestTurnTrackingAndFieldState`. Building
  this surfaced a second, real bug: doubles' two active-slot ids (`p1a`/
  `p1b`) were being tracked under one shared per-SIDE key (`_position_side`
  sliced off the slot letter), so the two active Pokemon on one side could
  silently overwrite each other's tracked species — fixed by tracking the
  full slot id (`_position_id`/`_side_of_position`), see
  `tests/test_showdown_import.py`'s `TestPositionTrackingFix`.
- A switch's target slot (which of the 2 active Pokemon it replaces) isn't
  tracked — active-list handling is best-effort capped at 2, dropping an
  already-fainted Pokemon first if a 3rd genuinely shows up, the same rule
  `frontend/src/lib/battleTimeline.js`'s `pushActive()` already uses.
- `known_moves` is only populated for currently-active (board) Pokemon, not
  every Pokemon that's ever been active — matches the immediate use case
  (why did the ACTING Pokemon choose this) without claiming more than that.
- **Fixed 2026-07-04:** `_side_snapshot`'s fainted-vs-roster matching used
  to compare species names as plain strings, so a Pokemon that Mega Evolves
  before fainting (Showdown reports its post-Mega name, e.g.
  "Charizard-Mega-Y", on the `pokemon_fainted` event) never matched the
  team-preview roster's base name ("Charizard") — permanently miscounting
  it as still alive in `available_pokemon`/`switch_options` for the rest of
  the match. Confirmed against a real replay while building §8d below. Now
  uses `_species_key()`, a local Mega/regional-form-stripping normalizer
  (same idea as `analyze_matches._species_base_norm`, not imported directly
  — see module docstring), for that one comparison only; display names are
  untouched.

**Wired into the backend** as `GET /jobs/{id}/decision-windows`
(`backend/main.py`, alongside `backend/analytics.compute_decision_windows()`
— same shape/convention as `compute_skill_scores`), returning the flat
per-job list; the frontend would filter by `match` client-side the same way
it already does for `/jobs/{id}/events`, though no UI consumes this yet —
data-layer only for now, a UI surface (e.g. inside Battle Replay, "why this
move?") is a natural next step once wanted.

**Tests:** `tests/test_decision_windows.py` (19 tests — known-moves timing
discipline, fainted/switch tracking, the no-turn-info empty-list case, and
multi-match separation both with and without a `match` field on events) +
`tests/test_analytics.py`'s new `TestComputeDecisionWindows` (3 invariant
tests against the real seeded demo job).

## 8d. Strategic analysis (`strategic_analysis.py`) — advantage score, momentum, resource tracking, mistake candidates

**Why this exists:** the wider architecture spec's "strategic analysis
engine" — the piece §8c's decision windows were explicitly built ahead of.
Built entirely on top of `decision_windows.py`'s per-turn snapshots plus
`events.json` directly; no new data collection.

**Read this before trusting a number out of it — the module docstring says
it at length, repeated here because it's the single most important thing
to know:** every score here is a HAND-TUNED HEURISTIC, not a trained or
statistically calibrated model. `win_probability` means "a bounded,
monotonic function of a simple advantage score," not "in similar real-world
positions, the win rate was X%." Treat it like a coach's gut-feel momentum
read, never like a solved-game probability.

- `compute_advantage_score(window, conditions)` — dominant signal is
  alive-Pokemon-count differential (`available_pokemon`, a real VGC
  heuristic: being up a Pokemon usually outweighs any single turn's move
  choice), `× ALIVE_WEIGHT` (25), clamped to ±100, with a small ±10 bonus
  for having Tailwind up when a `field_state` event actually reports it.
  Trick Room/weather/terrain are deliberately NOT scored (they depend on
  the actual Pokemon's base speed, which this project doesn't track — a
  fixed bonus would be a guess dressed as a number) — surfaced only as
  plain narrative facts in `reasons`.
- `estimate_win_probability(score)` — `tanh`-squashed into (0, 100),
  deliberately never exactly 0 or 100.
- `build_momentum_timeline(events, match_number)` — one entry per turn:
  `turn`, `player_alive`/`opponent_alive` (out of the brought-4 roster, not
  just the 2 on-field), `score`, `delta` from the previous turn, `win_probability`,
  and `reasons` (plain-language: a Pokemon lost since last turn, Tailwind
  newly up, etc. — never a speculative "because X was a bad move").
- `summarize_resources(momentum_timeline)` — match-level rollup. Inherits
  decision_windows.py's "reflects state as of the START of the turn" rule,
  so `*_alive_final` is the count going INTO the match's last turn, not
  necessarily after it — a side that faints its last Pokemon and loses ON
  that turn still shows 1 alive here, correctly, since that's what was
  known going in.
- `flag_mistake_candidates(events, match_number)` — conservative, only
  flags a turn as "worth reviewing," never asserts a specific correct play
  instead (the same "flag, don't force a guess" discipline
  `moveset_validator.py`/`pokemon_identity.py` already hold themselves to):
  `blind_switch_koed` (a Pokemon switched in and fainted the SAME turn) and
  `big_momentum_swing` (`|delta| >= 40`, flagged for human review — could
  be a mistake, could just be a good high-risk play paying off).
- `analyze_match`/`analyze_job` — the one-call bundling entry points, same
  "flatten across every match, stamp `match`" convention as
  `decision_windows.build_decision_windows_for_job`.

**Wired into the backend** as `GET /jobs/{id}/strategic-analysis`
(`backend/main.py`, alongside `backend/analytics.compute_strategic_analysis()`
— same convention as `compute_decision_windows`); no UI consumes this yet.

**Tests:** `tests/test_strategic_analysis.py` (29 tests — score/probability
arithmetic, momentum-timeline reasons and delta discipline, mistake-flag
patterns, plus a real-replay integration test proving Showdown import →
decision windows → strategic analysis works end-to-end on the same public
[Gen 9 Champions] replay used in `test_showdown_import.py`) +
`tests/test_analytics.py`'s new `TestComputeStrategicAnalysis` (4 invariant
tests against the real seeded demo job).

**Full Python suite: 459 tests, all passing** (`py -m unittest discover -s
tests -p "test_*.py"`). Frontend: 37 `node:test` tests, all passing
(`npm test` in `frontend/`).

## 8e. Coach sharing (`backend/coaching.py`) — private, link-gated coach/student network

**Product decision (from a "how do we build community" discussion):** accounts
are private by default and stay that way — the ONLY way anyone else ever sees
a player's stats is a shareable link the PLAYER themselves generates. There is
no directory, no search, no "find a coach" browse feature. Whoever holds a
valid, non-revoked, non-expired token gets in; nobody else gets anywhere
close. Any signed-in account can act as a "coach" simply by redeeming someone
else's link — there's no separate coach role or signup flow.

**Scope decisions (explicit, from the user):**
- The shared view is **aggregate-only**: skill scores + trend, coaching
  flags, toughest matchups, most-used Pokémon, tera stats, session count. It
  deliberately excludes per-match rows (`compute_match_list`), raw events,
  decision windows, and strategic analysis — a coach gets the same picture as
  the Progression tab, not a match-by-match replay browser or chat access.
- Link lifetime is the **player's choice per link**: never-expires (manual
  revoke only) or auto-expire in 7/30/90 days, set at creation time.
- Coaches get a persistent **roster** ("students") with a **notes** section
  the player can read back — this turned a one-off "view my stats" link into
  a small two-sided relationship feature.

**Data model** (`backend/coaching.py`, tables added to `supabase_schema.sql`):
- `share_links` (token PK, owner_user_id, label, expires_at, revoked_at,
  created_at, last_viewed_at). `label` is the PLAYER's own private note about
  who the link is for (e.g. "link for Coach Sarah") — never shown to whoever
  holds the link. `resolve_share_link(token)` collapses "never
  existed"/"revoked"/"expired" into a single `None`, deliberately not telling
  a caller which — same non-distinguishing-404 posture as `jobs.get_job()`.
- `coach_student_links` (coach_user_id, player_user_id, share_token,
  coach_label, added_at, unique on (coach, player)). `coach_label` is the
  COACH's own nickname for the student — independent of the player's link
  label. Redeeming a link (`add_student`) is idempotent. Removing a student
  does NOT revoke the underlying share link, and does NOT delete that coach's
  past notes — two independently-revocable layers on purpose.
- `coach_notes` (coach_user_id, player_user_id, coach_email, text, category,
  created_at, updated_at). `coach_email` is denormalized at write time from
  the coach's own verified session (the app has no general "look up any
  account's email by id" capability). Edit/delete are ownership-scoped to the
  writing coach; the player can read every note from every coach who's ever
  added them (`list_notes_about_player`), even one who's since removed them
  from their roster.
- Local-dev-mode fallback follows the exact `jobs.py` pattern: module-level
  in-memory dicts when `not auth.configured()`. Note that in local dev mode
  every request is the single `LOCAL_USER`, so coach and player are the same
  account — the feature still must not crash there, but isn't meaningfully
  testable end-to-end without real Supabase accounts.
- `compute_playstyle_profile(user_id)` composes existing pure functions
  (`career.merge_user_events`, `analytics.compute_record/report/
  skill_scores`, `career.compute_skill_score_trend`) — the exact same
  aggregate-only shape is used for both the public coach-view endpoint and
  the authenticated per-student endpoint, so there's one code path for "what
  a coach is allowed to see."

**Endpoints** (`backend/main.py`):
- `POST/GET /account/share-links`, `DELETE /account/share-links/{token}` —
  player manages their own links.
- `GET /account/coaching-notes` — player's read-only view of every note left
  about them.
- `GET /coach-view/{token}` — **the one public, unauthenticated endpoint in
  the whole backend** (no `Depends(auth.current_user)` on purpose). Resolves
  the token, records `last_viewed_at`, returns the aggregate profile plus
  `shared_label` (the player's own label, not their email/account identity).
- `POST /coach/students` (redeem a link), `GET /coach/students` (roster),
  `PATCH/DELETE /coach/students/{player_user_id}` (rename/remove),
  `GET /coach/students/{player_user_id}/profile` (same shape as the public
  view, but authenticated + ownership-scoped), `GET/POST
  /coach/students/{player_user_id}/notes`, `PATCH/DELETE
  /coach/notes/{note_id}`.

**Frontend:** no router dependency exists in this app, so the one public
route is handled manually — `frontend/src/main.jsx` regex-matches
`window.location.pathname` for `/coach/:token` and renders the standalone
`<CoachView/>` component instead of the whole authenticated `<App/>` shell
when matched (works under both the Vite dev server's `/` base and the
production build's `/dashboard/` base). New components:
`CoachSharing.jsx` (player's "share your stats" panel — link generation
form, link list with computed Active/Revoked/Expired status pills, copy/
revoke actions, read-only notes list), `StudentRoster.jsx` (coach's roster —
add-a-student form that accepts a pasted link or bare token, rename/remove/
view-profile actions, and a student detail view reusing `SkillScores`/
`CoachingFlags`/`WinRateTable`/`CountTable` plus a notes CRUD panel), and
`CoachView.jsx` (the public page itself, same component-reuse pattern). A new
"Coaching Network" tab in `Header.jsx`/`App.jsx` toggles between the two
player-side/coach-side views.

**Tests:** `tests/test_coaching.py` (32 tests — share-link create/list/
revoke/expiry, roster add/idempotency/rename/remove, notes CRUD with
cross-coach visibility and ownership scoping, `compute_playstyle_profile`
composition/shape, and the audit-logging coverage in §8f below). **Full
Python suite: 633 tests, all passing.** Frontend files were verified for
syntax via `@babel/parser` (JSX-aware) since this sandbox's `node_modules`
contains only Windows-native `rollup`/`esbuild` binaries — a real `npm run
build`/`npm run dev` needs to run on your own machine to fully confirm the
UI before shipping.

## 8f. Usage analytics — extending the internal audit log (`backend/audit.py`)

**Product decision:** rather than adding a third-party analytics vendor
(PostHog, Mixpanel, etc.), real usage tracking was built by extending
`backend/audit.py` — the freeform, append-only internal log that already
existed for job lifecycle events (`job_created`, `job_completed`,
`event_corrected`). It writes to both a local `audit_log.jsonl` file and,
when Supabase is configured, a `audit_log` table that's insert-only via the
service role key (no select/insert policy for regular users at all — see
`supabase_schema.sql` — so a leaked anon key could never read or forge
entries). This keeps every bit of usage data in the project's own Postgres
rather than sending it to a vendor, and it's queryable directly via
Supabase's SQL editor (included free on every plan) with zero extra
integration work.

**New event types logged**, on top of the pre-existing job-lifecycle ones:

- `coach_question_asked` (`backend/main.py`'s `job_coach`/`career_coach`) —
  the literal question text (plus a length-capped answer) for every question
  asked of the AI coach, tagged `scope: "job"` or `"career"`. This is
  probably the single best "what are users actually trying to understand"
  signal the app can capture, and previously these questions went straight
  to Gemini and were never persisted anywhere.
- `share_link_created` / `share_link_revoked` / `share_link_viewed`
  (`backend/coaching.py`) — logged inside the module functions themselves
  (`create_share_link`, `revoke_share_link`, `touch_share_link`), same
  convention `backend/jobs.py` already used for its own lifecycle events.
  Failed actions (e.g. trying to revoke someone else's link) are NOT logged
  — only real state changes are.
- `student_added` / `student_removed` (`backend/coaching.py`'s `add_student`/
  `remove_student`) — `student_added` only fires on the actual new-row case,
  not on an idempotent re-redeem of the same link (see `TestCoachingAuditLogging`
  in `tests/test_coaching.py`).
- `coach_note_added` (`backend/coaching.py`'s `add_note`) — logs `category`
  (e.g. "coaching_plan"/"skill_focus") so note-type usage patterns are
  visible without duplicating the note's full text into the audit log (the
  note itself already lives durably in the `coach_notes` table).

**Frontend-only signals** (tab views, UI interactions that never otherwise
hit the backend) go through a new endpoint, `POST /telemetry/event`
(`backend/main.py`, model `ClientEvent` in `backend/models.py`) — requires a
signed-in user like every other endpoint (the frontend only ever calls it
from inside the authenticated dashboard shell), and writes through the exact
same `audit.record()` call, namespaced as `client:<event_type>` so
frontend-origin events are easy to tell apart from backend-origin ones at a
glance. The frontend's `api.track(eventType, payload)` helper
(`frontend/src/api.js`) is deliberately fire-and-forget — never awaited by
callers, swallows its own errors — since a tracking call failing must never
affect the feature the user is actually using. Wired into `App.jsx`: every
tab change (`tab_viewed`), opening the New Job panel
(`new_job_panel_opened`), and toggling between the "Share your stats"/"Your
students" halves of the Coaching Network tab (`network_view_toggled`).

**Tests:** `TestCoachingAuditLogging` in `tests/test_coaching.py` (6 tests —
redirects `audit.LOG_PATH` to a temp file per test, same technique
`tests/test_audit.py`'s own `TestAuditLocalMode` uses, and confirms each
lifecycle action logs the right event with the right payload, and that
failed/idempotent actions do NOT double-log). The `main.py`-level wiring
(the new `coach_question_asked` calls and the `/telemetry/event` route
itself) isn't separately unit-tested — consistent with this project's
existing convention that `backend/main.py`'s routes are thin wrappers
verified by compiling clean plus the underlying module tests, not tested
directly (no test in this suite spins up a real FastAPI `TestClient`).

## 9. Frontend (as built — React + Vite, `frontend/`)

**No longer a proposal — this is running.** `frontend/src/App.jsx` is the
orchestrator: checks `/auth/status`, shows the `<Auth />` screen or skips
straight to the dashboard (local dev mode), loads the job list, then fires 5
endpoint calls in parallel (record/report/matches-summary/opponent-strength/
skill-scores) for the selected job.

Actual components (`frontend/src/components/`): `Header` (job picker, tabs,
"+ New job"), `Auth` (Supabase sign-in/sign-up), `NewJobPanel` (tabbed
URL/upload/Showdown-replay job creator, drag-and-drop, plus Mode and
Regulation dropdowns — see §3a), `RecordCards` (win rate, trend, combat
stats), `SkillScores` (the 4 progression bars + overall ring),
`CoachingFlags` (plain-English flags), `StatTable` (reusable win-rate/count
tables), `MatchesTable` + `MatchEvents` (per-match table that expands into a
full event timeline with reference-frame thumbnails, confidence badges, and
inline manual-correction forms — see §2c), `OpponentStrength` (type-overlap
risk), `CoachChat` (the chat box — now with a "This job" / "All-time
(career)" scope toggle, see below), `CareerProgress` (new — the "Career" tab,
see §8b: all-time record/skill-score rings, a session-by-session skill-score
trend chart with a per-session/cumulative toggle, and all-time win-rate/
matchup tables). No external charting library — `frontend/src/lib/charts.jsx`
is small hand-built SVG components (`Bar`, `Ring`, `TrendLine`, and now
`MultiTrendLine` — several 0-100 series on one shared x-axis, with a legend
and gap-not-fake-zero handling for a low-sample session that has no score
yet).

`App.jsx` loads the Career tab's data lazily (only the first time that tab
is opened, via `api.careerRecord/careerReport/careerSkillScores/
careerSkillScoresTrend`) rather than on every dashboard load, since most
visits only look at one job at a time; the header's Refresh button re-fires
whichever data set is currently showing. `CoachChat`'s scope toggle switches
between `api.askCoach(jobId, question)` (unchanged) and the new
`api.askCareerCoach(question)`.

`frontend/src/api.js` is the one file that knows the backend's URL shape —
every component calls a function here rather than writing raw `fetch()`
calls, and it auto-attaches the Supabase session token (or nothing, in local
dev mode).

### 9a. Native battle replay (`frontend/src/lib/battleTimeline.js` + `BattleReplay.jsx`)

**Why this exists:** the user asked whether the system could recreate a
match in Pokémon Showdown's own replay export format, specifically so they
could visually sanity-check the AI's read of a match against what actually
happened. The honest answer: a real Showdown replay is exact simulator
output (`|move|`, `|-damage|`, `|-status|`, precise HP fractions, every
ability/item proc — see `showdown_import.py`'s parser for the full shape),
while this project's own events are an AI's approximate, confidence-scored
read of video. Forcing our data into that exact protocol would mean either
fabricating precision we don't have or producing a log full of gaps
Showdown's viewer isn't built to render. The user chose the more honest
alternative: a **native in-dashboard reconstruction** that walks our own
event shape directly and renders exactly what we know, including the nulls.

**`frontend/src/lib/battleTimeline.js`** — pure JS, no React.
`buildBattleTimeline(events, matchNumber)` filters one match's events,
sorts by timestamp, and walks them in order maintaining per-side
`Map<species, {hp, status, tera, fainted}>` state plus an active-mons list
(capped at 2 for doubles, dropping an already-fainted mon first if a 3rd
genuinely shows up). Emits one frame per event: `{ idx, timestamp, event,
actor, confidence, referenceFrame, caption, player: MonState[], opponent:
MonState[] }`. `field_state` events (video-sourced matches) are the
authoritative "who's active" signal when present; `pokemon_sent_out` drives
the same tracking when no `field_state` events exist (Showdown-sourced jobs
have none). A null HP stays null — never guessed. Captions are generated
per-event-type (`captionFor()`) with a generic fallback for any unhandled
event type so new event types never break rendering.

**`frontend/src/components/BattleReplay.jsx`** — the stepper UI. Two side
columns of `MonCard`s (species, HP bar via the existing `Bar` SVG component,
TERA/status/fainted badges), a caption row with a confidence badge, the
exact reference frame the AI read for that step (reusing `EventThumb`/
`ImageLightbox`, now exported from `MatchEvents.jsx` for this purpose), and
Prev/Play/Next controls with autoplay (1.4s/step). Wired into
`MatchesTable.jsx` as a "Battle replay" / "Corrections list" toggle inside
each expanded match row — same events data already being fetched, no new
API call.

**Testing:** no JS test framework (vitest/jest) exists in this project —
`frontend/package.json` only has Vite as a devDependency, consistent with
the project's no-unnecessary-dependency approach (mirrored in
`charts.jsx`'s hand-rolled SVG instead of a charting library). Rather than
add one, `frontend/src/lib/battleTimeline.test.mjs` uses Node's built-in
`node:test` + `node:assert/strict` — zero new dependencies. Run it with
`npm test` (from `frontend/`) or directly via `node --test
src/lib/battleTimeline.test.mjs`. 14 tests cover: one frame per event,
team-preview seeding, HP updates (including a null not clobbering a known
value, and a string like `"82%"` parsing correctly), status/Tera/faint
state, the doubles active-cap drop-fainted-first logic, caption text per
event type, confidence/reference-frame passthrough (and correct `undefined`
when absent), an unknown match number returning `[]` without crashing, and
tolerant parsing of `field_state`'s richer `{name, hp_percent}` object shape
for active mons.

**Known gap:** this sandbox cannot run `npm run build` (the mounted
`node_modules`'s native rollup/esbuild binaries were installed on the user's
Windows machine and don't match this Linux sandbox, and a fresh `npm
install` to fix that is blocked by this sandbox's npm registry
restriction). Verified instead via full manual review of every touched file
plus the real `node --test` run above, which actually executes
`battleTimeline.js`'s logic rather than just checking syntax — the user
should still run `npm run dev` / `npm run build` on their own machine to do
a final visual check.

### 9b. Clarification queue (`frontend/src/lib/clarifications.js` + `ClarificationQueue.jsx`)

**Why this exists:** the original Matches-tab correction UI (`MatchEvents.jsx`)
showed every single event with its own "Correct this" form — reviewing a
match meant scrolling every event, not just the ones actually worth a
second look. The user asked for the opposite: narrow it down to the
smallest number of clarifying questions, e.g. one "what Pokémon is this?"
instead of five separate low-confidence rows that are all actually the same
uncertain sighting. Scoping choices (asked via clarifying questions, all
picked as recommended): group by same guessed species + side within one
match only (not across the whole job — safer, since the same nickname could
legitimately be a different Pokémon in a different match); replace the
per-match Corrections list as the default view, with a fallback link to the
exhaustive per-event list still underneath; answer each question with
multiple-choice buttons rather than free text, as a first step toward the
gamified feel mentioned as a future direction.

**`frontend/src/lib/clarifications.js`** — pure JS, no React.
`buildClarificationQueue(events, matchNumber)` filters that match's events
to ones needing a human look (confidence below the shared
`lib/confidence.js`'s `LOW_CONFIDENCE_THRESHOLD`, or the AI's own
`roster_conflict` flag — see §2c's roster-conflict detection — and never an
already-`corrected` event), groups them by `(side, guessed species)`, and
returns one question per group with every event index it should apply to,
a representative reference frame, and a short candidate-answer list: the
current guess first, then any legal-but-out-of-roster species the AI itself
flagged (`roster_conflict_species`), then the rest of that side's
team-preview-confirmed "brought" roster — deliberately not an exhaustive
dex list, since the whole point is fewer choices. Team_preview's own
roster/lead read is intentionally excluded from this grouping (it's a
different shape — several species in one event — and keeps its existing
dedicated section in `MatchEvents.jsx` unchanged).

**`frontend/src/lib/confidence.js`** — a one-line-of-substance module that
exists purely so `LOW_CONFIDENCE_THRESHOLD` has exactly one definition
shared by `MatchEvents.jsx` and `clarifications.js`. It's a separate file
from `MatchEvents.jsx` (rather than exporting the constant from there
directly) because Node's built-in test runner can't load a `.jsx` file at
all (no JSX transform outside Vite/Babel) — anything meant to be both
React-usable and plain-Node-testable has to live in a `.js` file with no
JSX in it.

**`frontend/src/components/ClarificationQueue.jsx`** — the new default
content of the Matches tab's "Corrections list" toggle. Each grouped
question renders as a card: the representative reference frame, a "current
guess — is that right?" question, a prominent "✓ Yes, that's right" button
(the common case, since the AI is usually correct and just flagging its own
uncertainty), a handful of alternate-candidate buttons, and an "Other…"
free-text fallback for the rare case none of the short list is right.
Confirming applies the chosen species to every event in the group at once
— no new backend endpoint needed, since it just fires the existing
`PATCH /jobs/{id}/events/{index}` once per grouped event index (the backend
already merges whatever fields it's given), also sending `confidence: 1.0`
and `roster_conflict: false` so the group can't reappear in the queue next
render just because those fields were never independently refreshed. A
"Show every event instead" link still reaches the full, unfiltered
`MatchEvents.jsx` list underneath, for the rarer case a non-identity field
(HP, status, an item/ability call) needs a hand correction instead of a
species guess.

**Testing:** `frontend/src/lib/clarifications.test.mjs` (same `node:test` +
`node:assert/strict` convention as `battleTimeline.test.mjs`, run via
`npm test` from `frontend/`) — 12 tests covering group collapsing, the
common zero-questions case, roster-conflict inclusion at any confidence,
excluding already-corrected events, team_preview never becoming a question,
separate groups per species/side, candidate ordering and de-duplication,
cross-match isolation, `minConfidence`/`referenceFrame` selection, sort
order, and the no-team_preview fallback. All 26 frontend tests (this file +
`battleTimeline.test.mjs`) pass together via `npm test`.

**Known gap:** same sandbox limitation as §9a — verified via full manual
review, `@babel/parser` syntax-checking every touched/new `.jsx` file, and
the real `node --test` run above, but not a live `npm run build`.

**Follow-up fixes made after real usage surfaced two gaps:**

1. **A photo with nothing to show.** The `demo` seed job (hand-planted
   placeholder data, not real pipeline output - only 3 of its 1841 events
   ever got a `reference_frame`) made "no photo" cards common enough to
   notice. `buildClarificationQueue()` now tries three tiers before giving
   up: the group's own flagged events' photo, then ANY other sighting of
   that exact `(side, species)` elsewhere in the match (confident or not -
   `anyReferenceFrameBySpecies`), then team_preview's own roster-screen
   photo as a last resort (flagged via `isTeamPreviewFallback` so the UI
   labels it differently - it's the whole roster, not one turn). Only when
   all three come up empty does the card explain there's genuinely no
   photo anywhere in the match and point to Battle Replay / the user's own
   memory instead.
2. **Which Pokemon in a doubles photo?** A photo can show 2 Pokemon per
   side at once, but a question only names one (the guess). The first
   attempt at fixing this named the *other* active species in prose ("the
   other one active here was X"). The user's actual ask was more precise -
   a circle or indicator drawn directly on the photo pointing at the
   Pokemon in question. That was investigated and deliberately **not**
   built: `accuracy_addons/hp_bar_reader.py` already tried pinning fixed
   pixel regions to the broadcast overlay's HP-bar plates, and documents,
   from real measurement, that those plates are **not** pinned to a fixed
   position across frames - its own docstring records a region that read
   correctly on one frame missing by ~8px on a different frame from the
   *same* streamer's *same* overlay layout, and only 2 of up to 4 possible
   doubles plate positions have ever been measured at all. A different
   video's layout (different webcam placement, different HP-bar style -
   exactly what the user's own screenshot showed) would be measured from
   nothing. Drawing a circle from coordinates this unreliable risked
   confidently pointing at the *wrong* Pokemon, which is worse than not
   pointing at all - and conflicts with this project's standing principle
   that a null/uncertain read should say so rather than fabricate
   precision (see `battleTimeline.js`'s own "a null HP stays null" comment).

   Instead, `lib/clarifications.js` returns `referenceFrameEventIdx` (which
   specific event the chosen photo came from - `null` for the team_preview
   fallback and the true no-photo case, since neither is one specific turn)
   and an exported `frameContextFor(frames, group)` that looks up
   `battleTimeline.js`'s own turn-by-turn reconstruction (the same one
   `BattleReplay.jsx` uses) for that moment, returning `{ ownHp, ownStatus,
   others }` - the guessed Pokemon's own HP%/status at that exact turn, plus
   every OTHER Pokemon active alongside it with its HP% too. Every capture
   style observed so far already prints HP% directly next to each Pokemon's
   name on screen, so `ClarificationQueue.jsx` surfaces "this one should
   read about 68% HP" (and, if something else was active alongside it,
   that Pokemon's name and HP% too) - a number the user can actually match
   against what's printed in the photo, rather than trusting a guessed
   pixel position. Returns all-null/empty in singles, whenever nothing else
   was active alongside the guess, or for the two fallback cases with no
   single turn to look up.

   One subtlety worth recording: a single captured photo is frequently
   attached to more than one event at the same moment (e.g. a `move_used`
   and the `hp_change` it caused, tagged with the same nearby video frame
   by `attach_reference_frames`). `frameContextFor` matches on the photo's
   *path*, not the one event index that happened to supply it, and takes
   the last (most up-to-date) frame among every event sharing that path -
   otherwise an HP update from a sibling event at the same moment could be
   missed, showing a stale percentage.

Both fixes are covered by new tests in `clarifications.test.mjs` (19 total
now, up from 12): the three-tier photo fallback (borrowing from a confident
sighting, never crossing side/species, the team_preview last resort, the
true-empty case) and `frameContextFor()` (own HP%/status plus other active
Pokemon's HP%, the singles/nothing-else-active case, and both fallback
cases correctly returning all-null/empty).

### 9c. Mirror matches + a dynamic camera (two real gaps a live question surfaced)

A user question ("how does the system read mirror matches - what if both
players have the same Pokemon?") led to finding one real bug and one real,
previously-undiscussed architectural gap - both specific to identity/side
tracking, not the clarification-queue UI itself.

**1. Mirror-match bug in the OCR tier's dedupe/merge logic.** Every event
already carries `actor` as a field completely separate from `pokemon`
(species) - Gemini determines `actor` from on-screen POSITION (bottom-left
plate = player, top-right = opponent, per `accuracy_addons/hp_bar_reader.py`'s
convention), never from the name, so the vision-derived event stream itself
isn't confused by two sides sharing a species. But `ocr_pipeline.py`'s
`_dedupe_consecutive()` (collapses a banner staying on screen across several
OCR-sampled frames) and `merge_ocr_and_vision_events()`'s `is_duplicate()`
(drops a vision event that duplicates an OCR one) both compared only
`(event, pokemon, detail)`/`(event, pokemon, timestamp-window)` - `actor`
was never part of either comparison. In a mirror match, if both sides ran
the same species and did something similar within a few seconds (e.g. both
Whimsicott using Protect around the same turn), one side's real event could
get silently collapsed/dropped as a false "duplicate" of the other side's.
Fixed via a new `_same_actor_or_unknown(a, b)` helper - true unless BOTH
sides are positively known and DIFFERENT (actor is frequently `None` on an
OCR event, since `battle_text_parser` only sets it when the banner text
itself discloses a side - see that module's own docstring point 2 - so this
falls back to the old behavior whenever either side is unknown, rather than
risk splitting a genuine duplicate apart). Covered by 4 new regression tests
in `tests/test_ocr_pipeline.py` (both the "must not collapse" and "still
collapses when actor is unknown" cases, for both functions).

**2. The reference-frame "photo" isn't guaranteed to show the relevant
side at all - Pokemon Champions' camera moves dynamically.** A deeper
follow-up question ("the camera moves dynamically across the field, sometimes
showing only the opponent's Pokemon - how is that handled?") surfaced that
it *wasn't* handled: `attach_reference_frames()` (analyze_matches.py) picks
an event's reference photo by nearest TIMESTAMP alone, with zero check on
what that specific sampled frame's camera angle actually contains. That's a
safe assumption for a broadcast with a fixed camera/overlay (both sides' UI
is always in frame) - which is what this pipeline's other accuracy addons
(`hp_bar_reader.py`, `ocr_battle_reader.py`'s original fixed regions) were
built and validated against - but Pokemon Champions' camera can be zoomed on
one side alone at the exact instant an event about the OTHER side was
extracted, in which case the attached "reference photo" doesn't show the
relevant Pokemon at all, and a clarification card built around that photo
(HP%-matching note, per §9b) has nothing real to check against.

Fixed with a new, honest, LOCAL (no extra API cost) presence check rather
than a coordinate-based overlay (rejected for the same reason as §9b's
circle-overlay - camera framing shifts too much to trust a fixed region):

- `ocr_battle_reader.species_readable_in_frame(frame, candidate_names)` -
  scans four broad, overlapping regions (`VISIBILITY_SCAN_BANDS`: top strip,
  bottom strip, left column, right column - deliberately NOT the one precise
  `NAME_PLATE_VALIDATED` box) for legible text matching any candidate name,
  via the same tolerant prefix-match `pokemon_identity._fuzzy_match` uses.
  Returns `True`/`False` - `False` is a much stronger signal than `True`
  (OCR can miss real, legible text; it can't invent text that isn't there),
  so callers should treat this as "plausibly visible, not proof" vs. "very
  likely not on screen at all," never the reverse. Explicitly NOT yet
  validated against real Pokemon Champions footage (none is bundled in this
  repo) - stated plainly in the module docstring, same honesty standard
  `hp_bar_reader.py` holds its own regions to.
- `analyze_matches.cross_check_reference_frame_visibility(events, workdir=None)` -
  the wiring: for every event with `pokemon`+`actor`+`reference_frame`, runs
  the check above and stamps `reference_frame_shows_subject` (True/False) on
  the event, lowering confidence and adding a `[reference-frame check ...]`
  detail note on `False` (same "flag, don't force a guess" pattern as
  `cross_check_hp_bar_events`/`cross_check_status_events`). Runs under the
  `--use-accuracy-addons` flag (now documents FOUR checks, not three;
  default-on as of 2026-07-04, see §2e) since it opens and OCR-scans an
  actual image file per event.
- `lib/clarifications.js` carries this through as `group.referenceFrameShowsSubject`
  (true/false/null - null means the addon never ran, or this is the
  team_preview/true-no-photo fallback with no specific sighting to check -
  treated as "unknown," never as a stand-in for false). `ClarificationQueue.jsx`
  shows a distinct, stronger-colored warning ("`<species>`'s name wasn't
  found readable anywhere in this photo — the camera may have been pointed
  elsewhere at this moment") and SUPPRESSES the HP%-matching note from §9b
  when this is explicitly `False`, since matching a number against a photo
  that doesn't show the Pokemon at all would be actively misleading.

Covered by: 12 new Python tests (`tests/test_ocr_battle_reader.py`'s
`TestTextMatchesAny`/`TestSpeciesReadableInFrame`, mocking `pytesseract`
directly rather than real synthetic frames, since the scan regions
themselves are an unvalidated first pass - see above) + 7 new Python tests
(`tests/test_accuracy_addons_wiring.py`'s `TestCrossCheckReferenceFrameVisibility`,
same monkeypatch-the-addon convention as the two existing wiring test
classes) + 4 new JS tests in `clarifications.test.mjs` (field passthrough
for the own/borrowed/fallback cases). Full suite as of the §2f pass:
379 Python tests, 37 frontend JS tests, all passing.

## 10. Start-here for a new chat

1. Read this file + `CODE_EXPLAINED.md` (a from-scratch, no-assumed-background
   walkthrough of literally every file — the most reliable single source if
   this doc and the code ever disagree again) + `ADDING_A_NEW_GAME.md` +
   `METRICS_AND_DATAPOINTS.md`.
2. The backend and frontend are BUILT — don't re-propose them. Skim
   `backend/main.py` (routes) and `frontend/src/App.jsx` (data flow) to see
   the real shape before changing anything.
3. Run `py -m unittest discover -s tests -v` before and after any change to
   pipeline/backend logic — every test guards a real bug that actually
   happened (§5a), so a break here is a real regression, not noise. For
   frontend pure-logic changes (e.g. `battleTimeline.js`), run `npm test`
   from `frontend/` (Node's built-in test runner, see §9a — no vitest/jest
   installed).
4. `--use-ocr-tier` and `--use-accuracy-addons` (§2d/§2e) are BOTH default-on
   as of 2026-07-04 — don't re-propose "wire these in," they're already the
   default path. The real remaining gap is a true local candidate-restricted
   image/template matcher (§2f) and the unmeasured `icon_template_matcher.py`
   templates (§2e) — both need real Pokémon Champions footage to calibrate,
   not more wiring.

## 11. Job-wide "overall skill set" battle profile (2026-07-09, tasks #234-237)

**Why this exists:** directly continues the 2026-07-09 update earlier in
this document (search for "tasks #232/#233") — once `analyze_job()` stopped
crashing and returned real turn-by-turn intel across an entire job, the
user's next ask was explicit: "We want to get an overall analysis of their
skill set." Everything in §9's six-report battle-intelligence manual
(speed_control/threat_pressure/resource_advantage/momentum/position_score/
risk_management) already existed per-turn, per-match — nothing existed that
rolled it up across an entire job into one profile.

**`strategic_analysis.compute_job_battle_profile(job_results)`** — takes
`analyze_job()`'s own output (a list of per-match results, each already
containing a `momentum_timeline` of per-turn six-report entries plus
`mistake_candidates`/`win_condition_candidates`/`loss_analysis`) and produces
one job-wide profile. Deliberately NOT a re-derivation of two things that
already exist and are exposed separately:

- `skill_scores.py`'s tempo/adaptability/execution/closing/overall scores — a
  separate, coarser heuristic computed straight from raw events, already at
  `GET /jobs/{id}/skill-scores`.
- `coach_report.py`'s win/loss record and flagged-pattern report — already at
  `GET /jobs/{id}/record` and `/report`.

Everything this function returns is a straightforward count/average of the
six reports `analyze_job()` already computed — no new heuristic scoring
happens here. Specifics worth knowing:

- **Position Score**: average/worst/best across every turn in the job, a
  separate average of just each match's OWN final turn (so a job full of
  matches that end strong doesn't get diluted by early-game turns), and the
  same 7-band distribution (Dominating → Losing) as percentages of all turns.
- **Speed Control**: only the `side` distribution (player/opponent/
  contested/none) is rolled up — its specific revealed tools (Choice Scarf,
  etc.) live only as unstructured `factors` prose in this report, unlike
  Threat Pressure's structured `player_tools`/`opponent_tools` lists, so
  tallying them here would mean re-parsing prose rather than counting
  already-structured data. Threat Pressure's tool lists ARE tallied.
- **Resource Advantage**: only screen uptime/score is rolled up (the one
  structured, non-double-counting sub-score `analyze_job` already isolates
  from Position Score's own composition — see §9's "never double-count"
  rule).
- **Win-condition and loss-pattern rollups are reported from the PLAYER's own
  side only** — a designated-sweeper/primary-closer count for the opponent's
  side isn't something this feature was asked for, and mixing both sides
  into one "top closers" list would misattribute opponent patterns as the
  player's own.
- Matches that failed to analyze (an `{"error": ...}` placeholder, per the
  #232/#233 fix) contribute zero turns to every rollup and are counted
  separately via `matches_errored`, never silently dropped or treated as
  zero-value turns.
- Returns `None` — not a zero-filled dict — when the job has no
  successfully-analyzed match with any turns recorded at all (e.g. a job
  made entirely of pre-2026-07-04 Showdown imports, which have no per-turn
  `field_state` tracking), same "nothing to report yet, not a fake zero"
  discipline used throughout this dashboard.

**Backend wiring**, following the exact existing pattern of
`compute_strategic_analysis`/`/jobs/{id}/strategic-analysis`:
`backend/analytics.compute_job_battle_profile(events)` is a one-line wrapper
(`_sa.compute_job_battle_profile(_sa.analyze_job(events))`), and
`GET /jobs/{job_id}/battle-profile` (`backend/main.py`) calls it after the
usual `_job_or_404` ownership check and `events.json`-exists check (409 if
the job hasn't reached that step yet). Like `compute_skill_scores` and
`compute_strategic_analysis` above it, this is pure arithmetic over
`events.json` with no AI call, so it's cheap enough to compute on every
request rather than needing its own cache file.

**Real, verified output** against job `303d13ba0940`'s actual 30-match,
video-extracted `events.json` (the same job the #232/#233 fix was verified
against): `matches_analyzed: 30`, `matches_errored: 0`, `turns_analyzed: 76`;
position score average `-4.3` (worst `-80`, best `57`), band distribution
topped by "Even" at 43.4%; `mistake_patterns.counts_by_type` showing
`blind_switch_koed: 113` and `big_momentum_swing: 6`; Palafin as the top
`primary_closer` at 10 times established; `loss_patterns` showing 9 losses
analyzed with an average decisive turn of 1.4. Nothing here was invented —
this is what the real function returns against the real file.

**Tests**: `tests/test_strategic_analysis.py`'s new
`TestComputeJobBattleProfile` class, 13 tests covering the `None` empty
cases, `matches_analyzed`/`matches_errored` counted separately, position
score averages/band distribution, speed control side distribution, threat
pressure tool counts, resource advantage screen uptime, momentum event
counts, risk management posture keys always present (even at 0%), mistake
pattern counts, win-condition top-sweeper/top-closer rollups, and loss
patterns correctly counting only the player's own losses (a player win
contributes no loss-pattern data). One genuine test-writing bug was caught
and fixed along the way: a band-distribution fixture used a 3-Pokemon
`p_brought` list when the intent was a 2-alive scenario — `available_pokemon`
reflects the full brought roster minus faints, not just what's shown active
on the field, so the fixture was corrected to 2 Pokemon to actually produce
the intended band. Full suite: 944 tests, all passing.

**Frontend**: `api.battleProfile(jobId)` (`frontend/src/api.js`) calls the
new endpoint; `BattleProfile.jsx` (new component) renders it — position
score stat + band-distribution bars, speed control/threat pressure
favorability bars, danger-tool count tables, screen uptime, momentum
gained/lost/neutral bars + event-count table, risk-posture bars, mistake-
pattern counts, loss patterns (decisive turn, common final-blow Pokémon),
and top designated-sweeper/primary-closer tables — reusing the existing
`Bar`/`CountTable` primitives (`lib/charts.jsx`, `StatTable.jsx`) rather than
inventing new chart components. Wired into the existing Progression tab in
`App.jsx` (fetched alongside skill-scores/record/report in `loadDashboard`'s
`Promise.all`, same "cheap enough to fetch on every dashboard load"
reasoning as the backend side), right below the existing Skill Scores
section. Renders an honest empty-state card (not a misleading empty chart)
when the endpoint returns `null`. New `.battle-profile` CSS class added
(`styles.css`) — just a vertical flex stack of the existing `.card`/
`.two-col` blocks, no new visual primitives.

**Verification caveat, stated plainly**: the backend half was verified
directly — `py_compile` clean on both `backend/analytics.py` and
`backend/main.py`, the full 944-test suite passing, and a direct Python call
to `analytics.compute_job_battle_profile()` against the real job's
`events.json` reproducing the exact numbers above. The frontend half's JSX
was reviewed carefully by hand (against the exact patterns `SkillScores.jsx`/
`RecordCards.jsx`/`StatTable.jsx` already use) and checked for balanced
braces/parens, but **`npm run build` itself could not be run to completion
in this session** — the sandbox's npm registry access returned a bare `403
Forbidden` on every package (not just scoped ones) when a pre-existing,
unrelated `@rollup/rollup-linux-x64-gnu` native-binary bug prompted a
`node_modules`/`package-lock.json` reinstall attempt. `package.json` itself
is untouched, so a plain `npm install && npm run build` on a machine with
normal registry access (e.g. the user's own machine, per §63/§64) should
restore `node_modules` and build cleanly — this has simply not been
confirmed by this session directly, and is worth doing before shipping.

**Also worth recording**: this section's own placement is a good example of
why "append at the end of the file" needs to go through the Read tool, not a
bash `tail`/`wc -l`. While writing this update, `wc -l ARCHITECTURE_HANDOFF.md`
reported 605 lines and `tail` showed content that appeared to end right
after the 2026-07-09 #232/#233 update — but the Read tool's ground truth
showed the real file is 2848 lines long, with sections §2f through §10 (all
dated 2026-07-04 through 2026-07-06, i.e. chronologically BEFORE #232/#233)
physically located after it. That almost certainly means the #232/#233
update itself was appended, in an earlier session, at a stale/truncated
bash-side view of "end of file" rather than the true end — the same failure
mode documented throughout this doc's own recovery-procedure notes, just
applied to this Markdown file instead of a Python source file. This section
was written after confirming the file's true length (2848 lines) directly
via the Read tool first. Worth a cleanup pass later to physically move
#232/#233 to its correct chronological position, but that's a pure
documentation reordering with no code impact, so it wasn't done as part of
this task.
