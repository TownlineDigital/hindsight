# accuracy_addons/

Three free, local (no live-API-per-frame call) accuracy tools, built as **standalone
additions** — nothing in the existing pipeline (`analyze_matches.py`, `ocr_pipeline.py`,
etc.) was edited, on purpose, since other work may be in progress on those files. Nothing
here is wired into the live pipeline yet; that's a deliberate next step for whoever picks
this up, not something silently half-done.

## What's here

- **`icon_template_matcher.py`** — OpenCV template matching for fixed on-screen icons
  (move-type icons, and eventually status conditions / weather-terrain banners / the Tera
  crown). Ships with 3 real, validated templates (water/fire/electric move-type icons)
  extracted from an actual captured frame.
- **`hp_bar_reader.py`** — reads HP% directly from the HP bar's pixel color/fill length,
  as a free cross-check against `ocr_battle_reader.py`'s text-based HP read.
- **`templates/move_types/`** — the 3 validated icon crops (`type_water.png`,
  `type_fire.png`, `type_electric.png`).
- **`moveset_validator.py`** — flags a move read as implausible when a species has never
  legally learned it (per Pokemon Showdown's own learnset data) — the same class of fix as
  `analyze_matches.reject_banned_species()`, applied to moves instead of species. See its
  own docstring for full detail.
- **`data/showdown_learnsets_starter.json`** — real learnset data for 15 species
  (bulbasaur through beedrill), transcribed directly from Showdown's own
  `data/learnsets.ts`. Small on purpose — see the moveset section below for why, and
  `tools/export_showdown_learnsets.js` for how to get full dex coverage.
- **`tools/export_showdown_learnsets.js`** — a Node script (uses the official `@pkmn/data`
  package) that does a complete, one-shot export of every species' learnset. NOT run in
  this dev session (npm was network-blocked here) — real, standard code, needs running +
  verifying in an environment with normal npm access.
- **`format_rules_validator.py`** — cross-checks `adapters/pokemon/doubles.json`'s
  hand-maintained format rules against Showdown's own current Champions format/ruleset
  data, to catch the rules going stale as VGC regulations rotate. See its own docstring.
- **`data/showdown_champions_formats.json`** — real data fetched from Showdown's
  `config/formats.ts`/`data/rulesets.ts`: the Champions format list and the "Flat Rules"
  ruleset definition (Species Clause, Mythical/Restricted Legendary ban, etc.).

## Overnight pass (2026-07-03) — what's new, all tested against real data

Four incremental, real-data-tested additions this session (see
`OVERNIGHT_REPORT.md` for the plain-language summary):

- **Burn status template** (`templates/status/status_burn.png`, new
  `templates/status/` category + `VALIDATED_STATUS_TEMPLATES` /
  `load_status_templates()` / `identify_status_icon()` in
  `icon_template_matcher.py`). Cropped 18×18 from a real frame
  (`jobs/3e46bb33364c/match_frames/match_2/b_00021.jpg`, a burned Hydreigon).
  Tested MORE than the 3 move-type templates: self-match 1.000 on its source
  frame **and** 0.94–0.98 on the 10 *other* frames in that match where the
  burn badge is present, vs 0.30–0.43 where it isn't — real cross-frame
  generalization with clean separation.
- **Player (bottom-left) HP-bar region** (`PLAYER_BOTTOM_LEFT_HP_BAR` in
  `hp_bar_reader.py`), measured from real pixels (HSV green-band scan), not
  assumed by symmetry. Validated at two real HP values: Rotom 157/157 → reads
  100%, and Rotom 69/157 (44% by on-screen text) → reads 51% (agrees within
  the ±8 coarse tolerance). Also documents a newly-found honest caveat: the
  opponent region reads 0% on a *different* frame (Scrafty 71%) because the
  overlay plate sits ~8px lower there — the plates are not pinned to a fixed
  pixel row, so both regions are validated for the plate position they were
  measured against.
- **`format_rules_validator.py` made regulation-layer-aware.** The section-3a
  refactor moved `banned_species_categories`/`terastallization`/`regulation`
  out of `doubles.json` into `adapters/pokemon/regulations/<id>.json`, which
  had silently regressed the Mythical/Restricted-Legendary ban check to a
  *spurious* mismatch. It now reads those fields where they live; re-run
  against the real files this session, that check is back to a correct MATCH.
- **Reg M-B re-fetch:** `config/formats.ts` re-fetched — Reg M-B is **still**
  not a distinct Champions entry in Showdown (only Reg M-A variants). Reported
  plainly; the exact-regulation check stays honestly NOT_CONFIRMABLE.

Still open / NOT done this session (honest): the full Showdown learnset export
(npm still 403; the 3.55 MB `learnsets.ts` returns empty via the fetch tool;
per-species APIs like PokeAPI aren't reachable under the fetch tool's
provenance rule) — so `moveset_validator`'s coverage is unchanged (still the
15 starter species, 3 of which — Charizard/Venusaur/Blastoise — do appear in
real match footage). The mechanism was re-confirmed working against that real
starter data this session. No learnsets were fabricated from memory.

## What's actually been tested (not just written)

Both modules were run against a real frame from this project's own captured footage —
`jobs/3e46bb33364c/match_frames/match_2/b_00021.jpg` — during development, not just
written and assumed to work:

- **Icon matching**: all 3 templates re-matched their own source frame at a perfect
  1.000 score, at the correct on-screen pixel location. Confirms the crop → grayscale →
  matchTemplate → threshold pipeline is correct. This is a "does the plumbing work"
  result, not yet a "does it generalize to other frames/lighting" result.
- **HP bar reader**: first attempt read back **0%** on a Pokémon actually at 94% HP — the
  region accidentally included the "94%" text label next to the bar, which broke the
  column scan. Fixed by narrowing the region to stop before the text and loosening the
  color thresholds slightly (the bar's rounded edge has a couple of genuinely
  anti-aliased pixels). After the fix: reads back **~100%** against a real 94% HP frame —
  close enough to agree within tolerance, but see the resolution caveat below.
- **Moveset validator**: fetched Showdown's real `data/learnsets.ts` (a subagent parsed
  the raw source into JSON, verified `json.load()`-clean), then ran real checks against
  it — `Charizard` + `Flamethrower`/`Dragon Claw` → correctly `True`, `Charizard` +
  `Thunderbolt` (a move it's never actually learned) → correctly `False` and flagged
  (confidence dropped, a note appended to `detail`), an unlisted species (`Pikachu`, not
  in the 15-species starter data) → correctly `None`, left untouched rather than
  wrongly rejected.
- **Format rules validator**: fetched Showdown's real Champions format config, then ran
  `cross_check_adapter_rules()` against the ACTUAL `adapters/pokemon/doubles.json` on disk
  (not a mock). Real result: doubles-format and Mythical/Restricted-Legendary-ban both
  came back `MATCH` — no staleness found, the hand-maintained file is currently correct.
  Species Clause, Terastallization, and the exact M-B-vs-M-A regulation came back
  `NOT_CONFIRMABLE` (honestly, not silently passed) — see the module's own docstring for
  exactly why each one couldn't be directly confirmed from this particular fetch.

## Known limitations (read before integrating)

- Only 3 of ~18 move types have validated templates. Status icons, weather/terrain
  banners, and the Tera crown aren't captured yet at all.
- The HP bar region is only validated for ONE of the four plate positions a doubles
  battle can show (opponent, top-right). The other three need their own real-footage
  measurement — don't assume symmetry.
- HP bar precision is capped by source resolution: at the pipeline's 640×360
  battle-sampling frames, the bar is only ~45–50px wide, so each pixel ≈ 2 HP%. This is
  good enough to catch a badly wrong OCR read, not to nail an exact number. Likely much
  more precise if fed the pipeline's 1280px OCR-pass frames instead — untested.
- Icon templates are scale-sensitive (matched at capture resolution, no multi-scale
  search) — re-extract at whatever resolution they'll actually be matched against.
- **Moveset data covers only 15 species** (bulbasaur through beedrill) — none of them are
  Pokemon that actually show up in this project's real VGC match footage. This proves the
  mechanism against real data; it is NOT production coverage. Run
  `tools/export_showdown_learnsets.js` (untested here — see its own header comment) to get
  the real dex, then point `moveset_validator.py` at its output.
- The moveset check is deliberately lenient ("has this species EVER learned this move, any
  generation/method") — it will not catch a move that's real for the species but illegal
  in the CURRENT regulation. That's a different, harder problem already partially owned by
  the hand-maintained format `rules` in `adapters/pokemon/doubles.json` — this module
  doesn't try to replace that.

## How to extend

Capturing a new template or region the same validated way:
1. Grab a real frame showing the icon/state you need (from `jobs/*/match_frames/` or a
   fresh run).
2. Crop tightly around just that element, save as PNG into `templates/<category>/`.
3. Register it (one line in `VALIDATED_TEMPLATES` for icons, or a new region constant for
   pixel-based reads like the HP bar).
4. Test it against the frame it came from first (should score ~1.0 / read back correctly)
   before trusting it on anything else.

## Species sprite reference library (2026-07-06)

- **`tools/fetch_species_sprites.py`** — standalone script (run by hand,
  not called by the pipeline) that downloads Pokémon Champions' own
  in-game team-preview icons (320 files, Bulbagarden Archives) into
  `templates/species/`, plus a `manifest.json` mapping each file to its
  species name/dex number/form. This is reference material for a FUTURE
  species icon-matcher (the same idea as `icon_template_matcher.py`, just
  not built yet for species) — no matcher reads these files today. Run
  `python accuracy_addons/tools/fetch_species_sprites.py` from
  `poc-starter/` to populate the folder (needs real internet access; see
  the script's own docstring and `ARCHITECTURE_HANDOFF.md` section 2i for
  why this couldn't be run directly in the environment that wrote it).
- **`tools/fetch_species_sprites.py`'s tests** —
  `tests/test_fetch_species_sprites.py` covers filename parsing and
  cross-checks the embedded dex-number map against the live
  `adapters/pokemon/regulations/m-b.json` species list (no network needed
  for the tests themselves).

## Suggested integration point

`ocr_pipeline.py`'s tiered flow (`extract_ocr_events` → OCR text → Gemini fallback only
for genuine ambiguity) is the natural place for these to plug in the same way: try the
free pixel/template read first, only spend a vision call when it's missing or disagrees
with the OCR text read. Not done here — left for a deliberate integration pass so it can
be reviewed against whatever's changed in `ocr_pipeline.py`/`analyze_matches.py` since
this was written.
