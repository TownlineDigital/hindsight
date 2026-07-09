# Adding a New Game — Reference Guide

How to onboard a new game (or a new mode of an existing game) into the analytics
pipeline. The whole point of the adapter design is that this is **small, repeatable
config work** — you are never rebuilding the system.

---

## The mental model (read this first)

The pipeline is layered. Each new game touches only the top two layers:

```
adapters/_core.json          ← UNIVERSAL. Never change this when adding a game.
adapters/<game>/game.json    ← NEW per game: that game's vocabulary + mapping to the core.
adapters/<game>/<mode>.json  ← NEW per mode: a tiny delta (e.g. singles vs doubles).
        │
        ▼
compose_schema.py            ← merges core + game + mode → schema.json   (don't edit; just run)
        │
        ▼
2_analyze_gemini.py          ← reads schema.json   (don't edit)
battle_record.py           ← reads the events    (only touch if "match" works differently)
```

**You add JSON, not code.** The extraction, the analyzer, and the composer stay the same.

---

## What you create for each new game

| File | Required? | What it is |
|------|-----------|------------|
| `adapters/<game>/game.json` | Yes, once | The game's event vocabulary, fields, and core mapping |
| `adapters/<game>/<mode>.json` | Yes, one per mode | A small per-format delta (active count, win condition, examples) |
| Accuracy grading on test clips | Yes | Validate + tune the notes/examples until it's reliable |
| Format-detector entry | Optional | So the game/mode is auto-selected (once the detector exists) |
| `battle_record.py` tweak | Only if needed | If the game's "match / round / win" concept differs from Pokémon's |

---

## Step-by-step

### Step 1 — Create the game folder
```
adapters/<game>/
```
Use a short lowercase name, e.g. `valorant`, `streetfighter`, `lol`.

### Step 2 — Write `game.json`
This is the game's vocabulary, shared across all its modes. Keys:

- **`game`** — display name (e.g. "Valorant").
- **`event_types`** — the list of events you want captured in this game's own words
  (e.g. `kill`, `plant`, `defuse`, `round_start`).
- **`core_mapping`** — map each game event to a universal concept from `_core.json`
  (`kill` → `unit_eliminated`, `plant`/`defuse` → `objective`). **Do not skip this** —
  it's what makes cross-game analytics work later.
- **`fields`** — extra fields this game needs beyond the universal ones
  (universal already gives you `timestamp, event, actor, detail, confidence`).
- **`notes`** — game-specific reading rules: what on-screen text/markers to look for,
  and the common confusions to avoid.

### Step 3 — Write a mode file `<mode>.json`
One per format/ruleset. Keep it a **delta**, not a full schema. Keys:

- **`display_name`** — what shows up as the schema's title (e.g. "Valorant — Competitive").
- **`mode`** — short name (e.g. `competitive`).
- **`event_types`** — only events that are *extra* for this mode (often empty).
- **`fields`** — only fields that are *extra* for this mode.
- **`notes`** — the mode's specific rules. **Critically: define exactly when a MATCH ends.**
  (This is the #1 source of bugs — be explicit. e.g. "first to 13 rounds wins the match.")
- **`example_output`** — 3–5 worked example rows. **These matter a lot** for accuracy;
  give realistic, correctly-labeled examples including a match-end row with the `winner`.

### Step 4 — Compose and run
```
py compose_schema.py --game <game> --mode <mode>
py 2_analyze_gemini.py --model gemini-2.5-flash
```
`compose_schema.py --list` shows everything available.

### Step 5 — Grade accuracy and tune (don't skip)
Run on a few short test clips, open `events.csv` next to the footage, and check it in
`grade_accuracy.csv`. When it gets something wrong, **fix it in the `notes`/`example_output`,
not in code**, and re-compose. Iterate until the events you care about are reliable.
This tuning loop *is* the work — expect a handful of passes per game.

### Step 6 — (Optional) Register it with the format detector
Once the format detector exists, add the game's visual signature so it's auto-selected
(e.g. "two teams of 5, a bomb timer, a round counter" → `valorant/competitive`). Until
then, you pass `--game`/`--mode` by hand.

### Step 7 — (Only if needed) Adjust the stats layer
`battle_record.py` assumes a "match" with one winner. If your game's unit of analysis
differs (e.g. rounds within a match, or best-of-3 sets), extend the stats script. Most
games map cleanly onto the existing match/winner model and need no change.

---

## Golden rules

1. **Never edit `_core.json` to fit one game.** If something feels universal enough to
   belong in core, add it as a new core concept — but keep it game-agnostic.
2. **Always fill `core_mapping`.** Every game event should map to a core concept; that's
   how "eliminations per minute" or "objectives won" work identically across games.
3. **Modes are deltas.** If a mode file is getting long, most of it probably belongs in
   the game module instead.
4. **Examples beat instructions.** A few correct `example_output` rows improve accuracy
   more than paragraphs of notes.
5. **Define match-end precisely.** Be explicit about what screen/condition ends a match
   vs. what's just a single elimination. Ambiguity here causes over-counting.
6. **Over-report + use confidence.** Collect generously and filter on the `confidence`
   field later, rather than dropping uncertain data at capture time.

---

## Worked mini-example: adding Valorant

`adapters/valorant/game.json`
```json
{
  "layer": "game",
  "game": "Valorant",
  "event_types": ["kill", "death", "assist", "spike_plant", "spike_defuse",
                  "ability_used", "round_start", "round_end", "match_end", "scoreboard_state"],
  "core_mapping": {
    "kill": "unit_eliminated",
    "spike_plant": "objective",
    "spike_defuse": "objective",
    "round_start": "round_start",
    "round_end": "round_end",
    "match_end": "match_end",
    "scoreboard_state": "state_snapshot"
  },
  "fields": {
    "agent": "the agent involved, if visible",
    "weapon": "weapon used for a kill, if visible",
    "round_score": "the round score shown (e.g. '7-5'), if visible",
    "winner": "match_end ONLY: 'player' team or 'opponent' team"
  },
  "notes": "Read the kill feed and round-score banner. A 'kill' is one elimination; the ROUND ends when one team is wiped or the spike resolves; the MATCH ends only when a team reaches the round target."
}
```

`adapters/valorant/competitive.json`
```json
{
  "layer": "mode",
  "mode": "competitive",
  "display_name": "Valorant — Competitive",
  "description": "5v5, first team to 13 rounds wins the match (overtime if 12-12).",
  "event_types": [],
  "fields": {},
  "notes": "MATCH-END RULE: the match ends only when one team reaches 13 round wins (or wins in overtime). A single round ending is 'round_end', NEVER 'match_end'. Emit one 'match_end' per match with the winning side.",
  "example_output": [
    {"timestamp": 5, "event": "round_start", "actor": "both", "detail": "round 1", "confidence": 0.9},
    {"timestamp": 38, "event": "kill", "actor": "player", "agent": "Jett", "weapon": "Vandal", "detail": "Jett killed an enemy", "confidence": 0.9},
    {"timestamp": 95, "event": "spike_plant", "actor": "player", "detail": "spike planted", "confidence": 0.85},
    {"timestamp": 1820, "event": "match_end", "actor": "player", "round_score": "13-9", "winner": "player", "detail": "Victory", "confidence": 0.95}
  ]
}
```

Compose and run:
```
py compose_schema.py --game valorant --mode competitive
py 2_analyze_gemini.py --model gemini-2.5-flash
```

That's the whole job: two small JSON files, then grade-and-tune. The core, the
extraction, the analyzer, and the composer are untouched.

---

## Per-game checklist

- [ ] Create `adapters/<game>/` folder
- [ ] Write `game.json` (event_types, **core_mapping**, fields, notes)
- [ ] Write at least one `<mode>.json` (display_name, notes with **match-end rule**, example_output)
- [ ] `py compose_schema.py --game <game> --mode <mode>`
- [ ] Run on 2–3 test clips and grade accuracy in `grade_accuracy.csv`
- [ ] Tune `notes` / `example_output`, re-compose, repeat until reliable
- [ ] (Optional) add the game's signature to the format detector
- [ ] (Only if the game's match/round model differs) extend `battle_record.py`
- [ ] Confirm `core_mapping` covers every event type (for cross-game analytics)
```
