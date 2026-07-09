# Metrics & Data Points — Play-Style Diagnosis, Coaching & AI Q&A

A comprehensive reference of what to capture and compute to (1) diagnose a player's
style, (2) coach them, (3) produce valuable reports, and (4) let them *ask the AI*
about their games. Written for Pokémon VGC doubles, but the structure generalizes.

It's organized in layers: **raw data → per-match derived → cross-match aggregates →
style diagnosis → coaching signals → what the conversational AI needs**, plus honest
notes on extraction feasibility and a build-priority order.

---

## Layer 1 — Raw data points (the captured event stream)

### Match frame (one per match)
- Match ID, video timestamp range, real duration, **turn count**
- Format / ruleset (e.g., Reg H doubles)
- Both full teams (the 6 shown in preview)
- Both **brought** sets (the 4 each side selects)
- Both **leads** (the opening 2)
- Result: winner, **margin** (how many of the winner's Pokémon survived — 4/3/2/1-0), how it ended

### Per-turn game state (the timeline — critical for coaching & Q&A)
- Turn number
- The up-to-4 active Pokémon (2 per side)
- **HP** of each active (% and exact if readable) + remaining bench count per side
- **Field conditions:** weather (sun/rain/sand/snow), terrain (electric/grassy/psychic/misty),
  Trick Room (on/off + turns left), Tailwind (per side + turns left), screens
  (Reflect/Light Screen/Aurora Veil), Gravity, Tatsugiri/other room effects
- **Status** on each active (par/brn/psn/tox/slp/frz/confusion)
- **Stat stages** on each active (Intimidate −1 Atk, Swords Dance, Icy Wind −Spe, etc.)
- **Tera state:** which Pokémon has Terastallized, into what type

### Per action (every move/decision)
- Acting side, Pokémon, **move name**, **target(s)**
- Move category (physical/special/status), spread vs single-target
- **Turn order** / who moved first (a read on relative speed)
- Outcome: **damage dealt** (% and/or exact), effectiveness (super/neutral/not-very/immune),
  **crit**, hit/miss, secondary effect applied, **KO(s)** caused
- **Protect/Detect** used (and whether it blocked an attack)
- **Switch** (voluntary) vs forced swap
- Item consumed/activated (berry, Booster Energy, etc.)
- Ability triggered (Intimidate, Drizzle, Protosynthesis, redirection, etc.)
- **Terastallization** event (turn, Pokémon, type)
- Redirection / Fake Out / Follow Me / Helping Hand usage

### Faints
- Which Pokémon, side, turn, cause (which move / status / recoil)

---

## Layer 2 — Per-match derived metrics

- Outcome + **margin** (Pokémon remaining at win)
- **Lead matchup** (your opening 2 vs theirs)
- Brought composition + its archetype
- **First KO** ("first blood") — who and when
- **KO sequence** and timeline (order Pokémon fell)
- **Tera usage:** which Pokémon, into what type, on what turn (early/mid/late)
- **Speed control used** (Tailwind / Trick Room / neither) and by whom
- Momentum: turns-to-first-KO, the biggest swing turn
- **Positional outcome:** did you win/lose from *ahead* or *behind*
- Decision tally: switches made, Protects made, predicts hit vs missed
- Match length in turns (fast offense vs grind)

---

## Layer 3 — Cross-match aggregates (the analytics & player profile)

### Performance
- Overall W–L and win rate
- Win rate **by lead pair**, **by brought core**, **by Tera choice**
- Win rate **going first vs second** (turn-order luck/skill)
- Average KO differential; average margin
- **Conversion:** win rate when ahead after turn ~3; **comeback rate** when behind
- Trend over time; win streaks/skids; variance/consistency

### Usage & preferences
- Team usage (which 6); **bring rate per Pokémon**; bring rate per matchup
- **Lead frequency + lead win rate**
- Move usage per Pokémon; signature lines/combos
- Tera target frequency, Tera **type** choices, Tera **timing** distribution
- Speed-control preference (Tailwind vs Trick Room vs natural speed)
- Protect rate; switch rate; Fake Out / redirection / Helping Hand usage

### Matchup intelligence
- Opponents/archetypes faced — the **meta you actually face**
- **Matchup matrix:** win rate vs each common Pokémon/archetype
- **Bogey list:** which Pokémon/teams beat you most
- Threat exposure: what you have no answer to

---

## Layer 4 — Play-style diagnosis (who you are as a player)

Indices computed from the above; combine into a style label.

- **Tempo (offense↔defense):** avg turns-to-first-KO, KOs/turn, Protect rate, switch rate
- **Speed-control identity:** Tailwind / Trick Room / natural / mixed
- **Aggression & risk:** low-HP attacks, crit/secondary fishing, sacrifice plays
- **Switch tendency:** high (reactive/positional) vs low (commit-and-attack)
- **Protect reliance**
- **Lead predictability:** entropy of lead choices — are you readable?
- **Bring adaptability:** do brings flex by opponent, or auto-pilot?
- **Tera tendency:** early/aggressive vs saved/reactive
- **Endgame skill:** conversion + comeback rates
- **Consistency:** variance across matches

→ Example output label: *"Aggressive Tailwind hyper-offense; low switch rate; predictable
leads (70% same pair); saves Tera until forced; strong when ahead, poor comebacks."*

---

## Layer 5 — Coaching signals (mistakes & improvement levers)

Each should be reported with **frequency + example matches/turns (timestamps) + a suggested fix.**

- **Bad brings:** brought cores / matchups with low win rate
- **Predictable leads** an opponent could prep against
- **Tera misuse:** poor timing, wrong target, or *lower* win rate with Tera than without
- **Over- / under-switching** relative to what the position called for
- **Mispredicts:** attacking into Protect, wrong target, walking into redirection
- **"Throws":** matches lost from clearly winning positions (ahead in KOs/HP, then lost) — high-value flag
- **Recurring loss patterns:** situations/Pokémon you keep losing to
- **Underused assets:** a Pokémon with high win rate that's rarely brought
- **Speed-control errors:** getting out-sped, not deploying TR/Tailwind when needed
- **Positioning errors:** leaving a Pokémon in vs a losing matchup

---

## Layer 6 — What the conversational AI needs (to answer "what should I have done?")

- **A reconstructable per-turn game-state timeline** per match (Layer 1 per-turn), queryable
  by match + turn — so it can reason about a *specific* position, not just a stat.
- **Full event log with timestamps** linked to the video moment.
- **The aggregated profile** (Layers 3–4) for trend/identity questions.
- **The transcript, time-aligned** (their stated reasoning) — for "why did I do that."
- **Grounding game knowledge:** type chart, mechanics, current meta threats and standard
  lines — so its advice is *correct*, not plausible-sounding (model knowledge + a reference KB).
- **Retrieval (RAG)** over the player's match history so it can cite specific games.
- A **position representation** rich enough (HP, field, speed order, remaining Pokémon, Tera
  availability) for the AI to evaluate alternative lines.

---

## Extraction feasibility (be honest about sources)

- **Easy from on-screen text:** Pokémon names, moves, HP%, super-effective/crit/faint text,
  weather/terrain/Tailwind/Trick Room banners, status icons, Tera crown + type, result screen.
- **Derivable from events:** brought/leads (from who appears), KO sequence, margins,
  turn order (from move order), most style indices.
- **Harder / needs care:** exact stat stages, exact damage rolls, precise speed tiers.
- **Not visible in video (needs external data or inference):** EV/IV spreads, exact damage
  calcs, opponents' hidden items/moves/sets, ladder rating (unless shown).
- **Transcript-only:** intent/reasoning, occasional names/outcome calls.

---

## Build-priority order

- **MVP (you mostly have this):** teams, brought, leads, moves, faints, HP, winner, basic
  usage + win rates.
- **Next:** per-turn field state (weather/terrain/Tera/speed control), KO sequence, margins,
  lead/bring win rates, matchup matrix, first style indices.
- **Advanced:** throw & mispredict detection, conversation-ready per-turn state + transcript
  fusion, full coaching-signal engine, the AI Q&A layer with retrieval.

---

### One design note
Most of these are **computed from the same event stream you're already building** — you don't
need a new capture system, you need (a) richer per-turn state in the events, and (b) an
analytics layer that rolls events up into these metrics. The per-turn game-state timeline is
the single most important addition, because it's what unlocks *both* the deep coaching signals
*and* the "ask the AI about turn 5" conversation.
