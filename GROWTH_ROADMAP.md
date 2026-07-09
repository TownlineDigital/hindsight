# Growth Roadmap — Consumer Insight, Feature Priorities, and a Duolingo-Style Phase 2

*Written overnight as a strategy document, meant to be read cold in the morning. It is
self-contained: it assumes you've internalized `PRODUCT_BRIEF.md`, `V1_SUMMARY.md`,
`METRICS_AND_DATAPOINTS.md`, and `ARCHITECTURE_HANDOFF.md`, but it re-states the decisions
it leans on so you don't have to hold four docs in your head at once.*

*This is a **writing/research** document. It creates no code and edits no existing file —
including `accuracy_addons/`, which a separate task is actively expanding tonight. Where it
touches an already-made decision, it says so explicitly and argues the change rather than
quietly contradicting the brief. It follows the honesty standard set in
`accuracy_addons/README.md`: real sources with links, uncertainty flagged, speculation not
dressed up as fact.*

---

## 1. Executive summary

The competitive-Pokémon analytics space is **not empty** — there's a live cluster of free
Showdown replay analyzers (VS Recorder, Reportworm, Pokékipe, the VGC Replay Analyzer
extension, Showdown Tier, MunchStats) that already give VGC players the core stats they ask
for: per-team win rate, lead-pair records, matchup breakdowns, Tera-type frequency, move
usage, and ELO-over-time graphs. This is both a warning and an opportunity. The warning:
raw stat tracking from Showdown replays is a **solved, commoditized, free** problem, so
"we track your win rate by lead" is not a wedge. The opportunity: every one of those tools
stops at *description* ("here's what happened"). None of them do trustworthy **coaching
from real video**, none turn the numbers into a **guided path to get better**, and none
close the loop by **re-measuring whether you actually improved**. That gap — description →
prescription → verified progression — is exactly the "Duolingo of competitive gaming"
thesis, and it's defensible in a way another stat page is not.

What players consistently praise in adjacent tools (Mobalytics, Blitz) is *personalized,
specific, actionable* feedback and a *cumulative picture of development across sessions*.
What they consistently punish is generic filler advice ("random guesses that don't help you
learn"), ad-choked/paywalled UX, and unfocused feature sprawl. The lesson maps cleanly onto
decisions you've already made: lead with the timestamped, specific coaching flag (your v1
"aha"), keep the interface clean, and don't build a generic content bank.

For v1, the honest must-haves are the things that make the coaching *trustworthy and
specific* — accurate extraction, timestamped flags tied to real match moments, the 4 skill
scores with their confidence tier, and the free Showdown on-ramp — plus **at least one
insight the free replay analyzers can't produce** (the AI coach explaining a *specific turn*
in plain language is that thing). Everything gamification-flavored — streaks, leagues,
placement tests, curriculum, reassessment — is **Phase 2, and gated behind accuracy being
solid**, because a progression system built on numbers users don't trust is worse than no
progression system at all.

The single most differentiated Phase 2 feature is **periodic reassessment**: after a player
spends a focus period working on a weakness, the system re-measures *that specific skill* and
shows a believable before/after — controlling for the real confounds (opponent-strength
variance, small samples) using the confidence-tier machinery you already built. That's the
feature no competitor has, it's the natural premium differentiator, and it's the strongest
retention hook in the whole plan because a reassessment is a *reason to come back*.

One headwind to plan around, not ignore: consumer sentiment toward "AI in games" is
sharply negative right now (a December 2025 Quantic Foundry survey found ~85% of players
below-neutral on generative AI in games). The defense is the positioning you already chose —
"instant, **trustworthy** analysis" grounded in the real match, not a chatbot vibe — but it
means marketing should foreground *accuracy and the player's own data*, and de-emphasize
"AI" as the headline.

---

## 2. Consumer insight & competitive landscape

### 2.1 The VGC-specific competitive set is real and mostly free

The most important finding is that competitive Pokémon players already have a mature set of
free analytics tools, almost all built on **Showdown replay parsing** — the exact same
free/instant on-ramp you've made a first-class v1 citizen:

- **VS Recorder** (`vsrecorder.app`, open-source by Pocolip) parses leads, picks, and
  results from Showdown replay links and surfaces win rates, usage stats, lead-pair
  analysis, matchup breakdowns, Tera frequency, and move-usage charts — plus team
  management, a damage calculator, per-Pokémon notes, and Bo3 set grouping for
  tournament-accurate records.
- **Reportworm** builds a team report with matchup detail, usage, and damage calcs against
  common threats.
- **Pokékipe** and **Showdown Tier** add replay-history corpora and individual-Pokémon
  win-rate tracking.
- **VGC Replay Analyzer** (Chrome extension) does PASRS-style analysis: usage/win rates,
  lead combinations, Tera frequency, matchup breakdowns by opposing team, and **ELO
  progression graphs over time**.
- **Pikalytics** and **MunchStats** cover the *metagame* side (usage %, common sets, teams)
  rather than your-own-replays.

Read that list carefully, because it defines the moat problem. Every capability in
`METRICS_AND_DATAPOINTS.md` Layers 2–3 (win rate by lead/bring, matchup matrix, Tera timing,
usage) **already exists for free** for Showdown players. Your Showdown import produces the
same numbers those tools do. So the Showdown on-ramp is correctly positioned as a *free
acquisition hook*, but it is **not** where the paid value or the differentiation lives — a
point the brief already implies (VOD is the deeper, eventually-paid product) and that this
research strongly confirms.

Sources: VS Recorder ([vsrecorder.app](https://vsrecorder.app/),
[GitHub](https://github.com/Pocolip/vs-recorder)), [Reportworm](https://reportworm.com/),
[Pokékipe](https://pokekipe.com/replay), [Showdown Tier](https://showdowntier.com/),
[VGC Replay Analyzer](https://chromewebstore.google.com/detail/vgc-replay-analyzer/ikildimeghigegckdcdjbedfapehdimm),
[Pikalytics](https://www.pikalytics.com/), [MunchStats](https://munchstats.com/tools/),
[Smogon VGC Tracker thread](https://www.smogon.com/forums/threads/pokemon-vgc-tracker.3783996/).

### 2.2 What players praise vs. punish in adjacent coaching tools

Because the VGC tools are mostly descriptive stat pages, the clearest signal on *coaching*
value comes from the larger MOBA/FPS analytics products, where the pattern is consistent:

**Praised:** *personalized, specific* insight that names a weakness and what to do about it;
a clean, navigable UI; and — the recurring differentiator — a **cumulative picture of
development across sessions** rather than isolated one-off reports. One Blitz review put the
value proposition precisely: the differentiated value over "just using OP.GG in a browser
tab" is "the integrated coaching pipeline — game-to-game feedback that builds into a
cumulative picture of your development," and it's worth it *for players who will actually
check their post-game analysis after every session*.

**Punished:** generic advice — Mobalytics reviews complain that some guides "contain random
guesses that don't help players understand and learn the game." Ad-choked, paywalled, buggy
UX — Blitz's most common complaint for years. And **feature sprawl** — expanding into more
games "paradoxically made the LoL experience feel less prioritized."

Three implications for you, all reinforcing existing decisions:

1. **Specific beats generic, every time.** Your v1 "aha" (a timestamped, specific mistake)
   is exactly the right instinct; the failure mode to guard against is the coach chat or the
   flags drifting into plausible-sounding filler. This is *the same* "flag, don't force a
   guess" discipline `accuracy_addons/` already applies to extraction, applied to advice.
2. **The cumulative-development picture is the retention engine** — which is precisely what
   your skill scores + confidence tier + trend are for. That's your structural advantage
   over one-shot replay reports.
3. **Scope discipline is a feature.** The tools users resent are the bloated ones. Your
   "be ruthless" v1 scope and the deferral of coach/team/streamer features are correct;
   Section 4 flags where the roadmap risks re-introducing sprawl.

Sources:
[Mobalytics blog](https://mobalytics.gg/blog/10-things-you-can-learn-challenger-coach-profile-reviews/),
[Mobalytics on Trustpilot](https://www.trustpilot.com/review/mobalytics.gg),
[GameBoostingHub Mobalytics review](https://gameboostinghub.com/reviews/mobalytics/),
[Blitz.gg overlay review — Wombo Combo](https://www.wombocombo.gg/blog/game-analytics/blitz-gg-overlay-review).

### 2.3 The AI-sentiment headwind

Consumer attitudes toward "AI in games" are currently hostile. A December 2025 Quantic
Foundry survey (newer than the one already referenced in this project's chat history) found
**~85% of players below-neutral on generative AI in games, with 63% picking the *most*
negative option** — though attitudes vary by gender, age, and gaming motivation, so it's not
uniform. Broader data shows Gen Z AI *usage* steady but *skepticism* climbing. The concerns
cluster on gen-AI as a labor/monetization instrument and on low-trust "slop," not
specifically on analytical tools that help a player understand their own data.

This is a **positioning** problem, not a reason to abandon the AI coach. The mitigation is
already latent in your north star — "instant, **trustworthy** analysis" — and in the
engineering culture visible in `ARCHITECTURE_HANDOFF.md` (roster-locking, OCR-over-guessing,
the accuracy addons). Practical guidance: market *accuracy, specificity, and the player's own
match data* as the headline; treat "AI" as an implementation detail, not the hook. "It read
your actual games and can explain turn 5" survives the skepticism; "AI coach" as a banner
invites it.

Sources:
[Quantic Foundry, Dec 2025](https://quanticfoundry.com/2025/12/18/gen-ai/),
[Gallup — Gen Z AI adoption/skepticism](https://news.gallup.com/poll/708224/gen-adoption-steady-skepticism-climbs.aspx).

---

## 3. What stats/features players care about most (mapped to the metrics doc)

Prioritized by how often players actually ask for it and how much it drives the
"understand and improve" loop, with the `METRICS_AND_DATAPOINTS.md` layer that already
covers it — and honest gaps called out.

**Tier A — table stakes (players expect these; the free tools all have them)**

1. **Win rate, overall and by lead pair and by brought core.** → Layer 3 (Performance /
   Usage). Fully covered.
2. **Matchup matrix / bogey list — "what beats me most."** → Layer 3 (Matchup
   intelligence). Covered, and repeatedly the single most-requested VGC analytic.
3. **Lead usage + lead win rate, with a predictability read.** → Layer 3 (Usage) + Layer 4
   (Lead predictability entropy). Covered — and the entropy angle is *more* than the free
   tools offer, which mostly show frequency without framing it as "you're readable."
4. **Tera type/timing frequency and win rate by Tera choice.** → Layers 2–3. Covered.
5. **ELO / rating progression over time.** → **Gap.** The VGC Replay Analyzer graphs ELO
   over time; `METRICS_AND_DATAPOINTS.md` tracks trend/streaks/variance but treats ladder
   rating as "not visible in video (needs external data)." For Showdown-sourced matches the
   rating *is* in the replay data and players expect the graph. Worth capturing explicitly
   for Showdown imports even though video jobs can't produce it.

**Tier B — the differentiators (where you can beat the free tools)**

6. **Specific, timestamped mistake flags with a suggested fix.** → Layer 5 (Coaching
   signals). This is your wedge; no free replay analyzer does plain-English "here's the
   turn, here's what went wrong, here's the fix."
7. **"Throw" detection — games lost from winning positions.** → Layer 5 (flagged
   high-value) + Layer 2 (positional outcome). *Partially* covered as a metric; honestly
   flagged in `ARCHITECTURE_HANDOFF.md` §7 as **not yet built** (KO-attribution /
   loss-pattern analysis). High player value, real build cost.
8. **Conversational "what should I have done on turn 5?"** → Layer 6. This is the feature
   that most cleanly can't be commoditized by a stat page, because it requires the
   reconstructable per-turn state you've architected for.
9. **Skill identity / play-style label** ("aggressive Tailwind HO, predictable leads, poor
   comebacks"). → Layer 4. Players love a mirror; this is cheap to present and sticky.

**Tier C — nice, but not why anyone pays**

10. Damage calc integration, team-import/Poképaste, per-Pokémon notes, Bo3 grouping. →
    Mostly *outside* `METRICS_AND_DATAPOINTS.md` (they're team-building utilities, not
    diagnosis). The free tools bundle these; matching all of them is a scope trap (Section
    4). A damage calculator especially is a whole separate product that VS Recorder already
    does well — integrate/deep-link before you reinvent.

**Real gaps in the metrics doc worth naming:**

- **Ladder-rating capture for Showdown sources** (see A5) — the doc under-weights it because
  it was written video-first.
- **Best-of-3 / set-level records.** Tournament VGC is played in sets; VS Recorder makes Bo3
  grouping a headline feature. `METRICS_AND_DATAPOINTS.md` is match-centric and has no notion
  of a set. If the audience is tournament-aspiring players, this is a genuine modeling gap,
  not just a UI nicety.
- **Opponent-strength normalization as a first-class, surfaced number.** The backend has
  `opponent-strength` (type-overlap risk) and a confidence tier, but neither is yet framed as
  "your win rate, adjusted for who you faced." This matters enormously for Phase 2
  reassessment (Section 5) and is arguably the most important gap on this list.

---

## 4. Required functionality checklist

"What this tool needs to actually be worth paying for," split by horizon and written to
respect the existing v1 scope. **Worth-paying-for** is the lens: since the free tools already
give away descriptive stats, the paid line has to sit at *prescription and verified
progression*.

### Must-have for v1 (already in scope — protect these, don't add to them)

- Accurate extraction you can trust — the accuracy work (`accuracy_addons/`, OCR tier,
  roster-locking) is the foundation of *every* claim the product makes. Trust is the product.
- The 4 skill scores + confidence tier + trend on the dashboard.
- At least one specific, timestamped coaching flag per analyzed set (the "aha").
- AI coach chat grounded in the real per-turn timeline.
- Free Showdown import as the zero-friction on-ramp.
- Match history → per-match timeline with reference-frame thumbnails and manual correction
  (already built — and the manual-correction path is itself a *trust* feature; keep it
  visible).
- Usage-analytics instrumentation from day one (already decided — this is how Phase 2
  priorities get chosen from data instead of guesses).

**Scope-creep flags for v1 (things that feel v1 but are traps):** damage calculator, team
builder / Poképaste import, Bo3 set grouping, ELO graphs, opponent scouting. Each is real
player value and each is a *different product surface* the free tools already own. Pulling
any of them into v1 re-creates exactly the sprawl users punish Blitz for. Defer, and where
possible **deep-link to VS Recorder et al.** rather than rebuild.

### Should-have soon (v1.1–v1.5, before Phase 2 curriculum)

- **"Throw"/loss-pattern detection** (Layer 5; `ARCHITECTURE_HANDOFF.md` §7 lists it as not
  built). This is the highest-value *diagnostic* still missing and it directly feeds Phase 2
  focus-area generation.
- **Opponent-strength-adjusted win rate**, surfaced as a real number (Section 3 gap). Needed
  before reassessment can be believable.
- **Ladder-rating capture + progression graph for Showdown sources** (cheap; players expect
  it).
- A **QA pass on `showdown_import.py` against several real replays** (currently verified
  against one — `PRODUCT_BRIEF.md` §9 flags this as due diligence before real beta users).
- Wiring `accuracy_addons/` into the live tiered pipeline (the known "built but not
  integrated" gap, §2e/§7 — happening on a separate track).

### Later / nice-to-have (Phase 2+ and beyond)

- Duolingo-style progression: streaks-on-review, percentile league, placement assessment
  (Section 5).
- **Periodic reassessment** (Section 5 — the marquee Phase 2 feature).
- Set-level (Bo3) modeling if the tournament audience proves dominant in the usage data.
- Mobile (view + chat + "analysis ready" notifications only, per the brief).
- Coach/team/streamer features, opponent scouting, external meta ingestion (Pikalytics ToS
  blocks scraping — noted in `ARCHITECTURE_HANDOFF.md` §7).

---

## 5. Phase 2 vision: a Duolingo-style curriculum & training plan

### 5.0 The sequencing gate (read this first, it governs everything below)

**None of Phase 2 ships until accuracy is solid.** This is not a stylistic preference; it's a
dependency. Every Phase 2 mechanic — a curriculum focus area, a skill-score delta, a
before/after reassessment — is a *claim about the player's real play*. If the underlying
extraction is wrong, the curriculum tells someone to fix a weakness they don't have, and the
reassessment "improvement" is extraction noise. A gamified layer on untrustworthy numbers is
**worse than no layer**, because it converts a quiet data-quality problem into a loud,
confident, wrong coaching product — and it burns the one thing (trust) that Section 2.3 says
is your only defense against AI skepticism.

Concretely, the gate is: `accuracy_addons/` integrated and validated in the live pipeline,
"throw"/loss-pattern detection built, and skill scores stable enough that re-analyzing the
same matches yields the same scores. Until then, Phase 2 is design work, not shipped code.
The rest of this section describes what to build *after* that gate, and is deliberately
written as a plan-on-paper, not a green light.

### 5.1 What "curriculum" means here (respecting the no-quiz-bank decision)

The brief is emphatic and correct: **no separate hand-authored quiz/lesson content system.**
All progression is computed *from the player's real match data*. This document does **not**
propose an exception to that. "Curriculum" here means a **generated focus queue**, not a
content library:

> The system reads the player's own coaching flags (Layer 5) and skill-score drivers (Layer
> 4 → `skill_scores.json`'s `drivers`), identifies the weakness with the most upside, and
> renders it as a focus area built entirely from *that player's real moments*.

Worked example, entirely data-derived:

> **Your Adaptability score is low.** The driver: your leads are 70% the same pair
> (lead-entropy, Layer 4), and your brought composition barely changes by opponent. Here are
> **3 real moments from your matches** where a different lead would plausibly have helped
> (each links to the actual turn + reference frame). **Focus for your next 10 games:** vary
> your lead against Trick Room teams — you're 2–7 into them (matchup matrix, Layer 3).

Nothing there is authored content. The "lesson" is a query over the player's own events plus
the grounding game-knowledge KB the coach already uses (Layer 6). The "drill" is a
*constraint on their next real games* ("try a different lead"), not a synthetic minigame —
which is the only kind of practice that fits a game where reps come from real ladder/tournament
matches, not from an app-generated exercise. This keeps you on the right side of the
no-content-bank decision while still delivering the *felt experience* of a curriculum.

### 5.2 Which Duolingo mechanics translate — and which honestly don't

Duolingo's retention is real and measured (streaks make users ~3× more likely to return
daily; gamification helped cut churn from 47%→28% in major markets per published case
studies). But the mechanics work because language learning has a property competitive gaming
**doesn't**: an infinite supply of on-demand, self-generated practice reps. You can do a
Duolingo lesson at 2am on the bus. You cannot "do a VGC rep" on demand — a rep is a real
match against a real opponent, on their schedule, not yours. Every translation decision below
turns on that one difference.

| Duolingo mechanic | Verdict | Adapted form for a coaching app |
|---|---|---|
| **Daily bite-sized lessons** | ✗ Doesn't translate | You can't manufacture a match. Don't fake it with quizzes (violates the no-content-bank rule *and* rings hollow). Replace with: **"review one flagged moment from your history"** as the daily bite-sized unit — a real 60-second action that exists even on a no-games day. |
| **Streaks** | ~ Partial | A *play* streak punishes people for having a life (and for a game gated on opponents). A **review streak** — "you reviewed a match insight N days running" — is honest, always-achievable, and reinforces the habit reviews (Section 2.2) that actually drive improvement. Tie it to reviewing, never to playing. |
| **Leagues / leaderboards** | ~ Partial, later | Powerful, but has a hard **cold-start problem** (Section 8): a percentile is meaningless until there's a real population. Ship as **"you vs. the population" percentile on each skill score** *once* there's enough users, framed as skill-percentile, not a weekly promotion/demotion ladder (weekly ladders reward grinding volume, which you can't supply). |
| **Placement test** | ✓ Translates well | This is the *cleanest* fit and you've already built its skeleton. The first N matches → initial skill scores + confidence tier **is** a placement test. Lean into that framing explicitly: "your first 25 matches place you; come back to see the scores firm up." The confidence tier *is* the placement-confidence meter. |
| **Spaced repetition** | ~ Reframed | You can't re-serve a "card." But you *can* re-surface a **recurring weakness** the player hasn't improved — "this is the 4th match you lost to Trick Room; still your top bogey." That's spaced repetition of *attention*, driven by real recurrence, not a review scheduler. |
| **Hearts / loss-aversion / lives** | ✗ Skip | Punitive-scarcity mechanics fit a free-to-play funnel, not a paid coaching tool for people who already lose real games and feel it. Loss aversion here risks feeling like the app is punishing you for losing — exactly the "punitive not motivating" risk in Section 8. |
| **XP as shared currency** | ✓ Translates | A single "progression" currency earned by *analyzing matches and reviewing insights* (not by playing) can feed streak + placement + percentile coherently, the way Duolingo's XP feeds streak + league + achievements. Cheap, coherent, honest. |

Net: **placement, review-streaks, spaced *attention*, and an XP-style currency translate.
Daily lessons, play-streaks, weekly ladders, and hearts don't** — and the adaptations above
are how you get the retention benefit without the dishonest or ill-fitting version.

Sources:
[Duolingo gamification case study — Trophy](https://trophy.so/blog/duolingo-gamification-case-study),
[StriveCloud on Duolingo retention](https://www.strivecloud.io/blog/gamification-examples-boost-user-retention-duolingo),
[Duolingo blog — spaced repetition](https://blog.duolingo.com/spaced-repetition-for-learning/),
[Duolingo blog — placement test](https://blog.duolingo.com/partial-credit-improvements-to-duolingos-placement-test/),
[The PM Repo — Duolingo MAU/habit](https://www.thepmrepo.com/articles/how-duolingo-gamified-monthly-active-users-lessons-in-habit-formation).

### 5.3 Periodic reassessment design (the feature you specifically asked for)

The core idea: after a player spends a *focus period* working on a targeted weakness, the
system re-measures **that specific skill** and shows a credible before/after — not just the
same dashboard number with a new value, but an honest answer to "did the thing I worked on
actually improve?" This is the feature no competitor has, and it's the strongest
re-engagement trigger in the plan.

**When to reassess: match-count-based, not time-based.** Time-based reassessment ("check back
in 2 weeks") re-inherits the daily-lesson problem — it assumes a rep supply the player doesn't
control. Trigger on **completed matches within the focus area** instead: "you've played 10
more games since we flagged your leads — let's re-check Adaptability." This also naturally
gates the reassessment behind enough new sample to say anything (below).

**Isolating "did the targeted skill actually improve" from noise.** This is the hard part and
the place to be most honest, because three confounds will otherwise manufacture fake progress:

1. **Small-sample noise.** A skill score off 10 games is a high-variance estimate. This is
   exactly what your **confidence tier already models** (25 = good understanding, 50 = strong,
   100 = exceptional). The rating-systems literature backs the specific thresholds: in Glicko,
   a new player needs ~30 games to reach a *reliable* rating (deviation < 100), and RD only
   drops below ~50 ("very confident") after sustained play — i.e. **you cannot honestly claim
   improvement from a 5-game delta.** Rule: **don't report a before/after until the "after"
   window has enough matches to move the confidence tier meaningfully**, and always show the
   uncertainty, not just the point estimate.
2. **Opponent-strength variance.** A score can rise because you improved *or* because you
   drew weaker opponents. This is why the **opponent-strength-adjusted win rate** (Section 3/4
   gap) is a hard prerequisite for reassessment, not an optional nicety. Reassessment must
   compare *adjusted* performance, and should surface the adjustment ("your opponents were
   slightly weaker this window, so we've discounted the raw gain").
3. **Regression to the mean / cherry-picking the metric.** If you flagged the weakness *because*
   it was at a low ebb, some rebound is statistical, not skill. Mitigate by (a) pre-registering
   the target metric when the focus period *starts* (so you're not fishing for whichever number
   went up), and (b) reporting the change against the player's own longer-run baseline, not
   against the single worst window.

**What a believable before/after looks like.** Not "Adaptability 41 → 58 🎉". Instead:

> **Focus: lead predictability (started 12 games ago).**
> Lead entropy: **0.9 → 1.6 bits** (you used 5 distinct leads vs. 2 before).
> Adaptability skill score: **41 → 52**, confidence now *good understanding* (25+ games).
> Opponent strength this window: comparable (no discount needed).
> vs. Trick Room specifically — your flagged bogey — **2–7 → 5–4.**
> **Honest read:** real, moderate improvement on the thing you targeted; still a small sample,
> so treat it as "trending up," not "solved."

The believability comes from: naming the *specific* driver metric you targeted (not the
headline score alone), showing the confidence context, disclosing the opponent-strength
check, and *refusing to over-claim* on thin data. That refusal is the same discipline as the
`accuracy_addons/` "NOT_CONFIRMABLE rather than a false pass" ethic — applied to progress
claims.

**Why this drives retention.** A reassessment is a *scheduled reason to return* that the app
generates from the player's own behavior: finish the focus games → get told whether you
actually improved. It's the loop the whole "come back after your next session" thesis needs,
and unlike a streak it's intrinsically meaningful (it answers a question the player genuinely
has). The pre/post structure is also exactly how the sports- and esports-coaching literature
measures whether coaching worked (quasi-experimental pre-test/post-test designs), so the
framing is defensible, not just a growth gimmick.

Sources:
[Glickman — the Glicko system](https://www.glicko.net/glicko/glicko.pdf),
[Glicko rating system — Wikipedia](https://en.wikipedia.org/wiki/Glicko_rating_system),
[Glicko: When Confidence Matters](https://mcginniscommawill.com/posts/2025-04-29-glicko1-rating-system/),
[Rethinking performance measurement in esports (Sagepub, 2026)](https://journals.sagepub.com/doi/10.1177/17479541251378643),
[Sport coaches' perceived performance (MDPI Sports)](https://www.mdpi.com/2075-4663/13/3/83),
[Deliberate practice in medical simulation — StatPearls](https://www.ncbi.nlm.nih.gov/books/NBK554558/).

---

## 6. Monetization tie-in

This stays fully consistent with the direction already established (real Gemini cost
~$0.60–1.30 per hour of VOD; a flat "unlimited" sub under ~$15/mo loses money on real usage;
so an **hour-based credit model (~$2.50–4.50/hr)** or a **capped monthly allotment + paid
top-ups**, with **free Showdown import as the unlimited zero-cost hook**). Curriculum and
reassessment don't change that structure — they make the *paid* side more valuable.

- **The free tier stays honest and generous:** unlimited Showdown import, skill scores,
  placement, review-streaks. This is the acquisition engine and it costs ~$0 to serve. Do
  **not** paywall the progression basics — that's the Blitz mistake users punish.
- **VOD analysis remains the metered, paid path** (hour/credit-based), because it's where the
  real Gemini cost is and where the deepest coaching (timestamped video flags, "explain turn
  5" over *your footage*) lives.
- **Reassessment is the premium differentiator.** A *basic* reassessment (does my score move?)
  can be free on Showdown data. The *deep* reassessment — opponent-adjusted, driver-level,
  before/after over analyzed **VOD** with the specific moments pulled — naturally consumes
  VOD credits and is worth paying for precisely because no free tool can do it. It also
  increases credit consumption in a way the user *wants* (they're buying proof they improved),
  which is a healthier monetization loop than gating basic access.
- **Curriculum focus areas** likewise: generating the focus area is cheap (a query over
  existing data); the *coached execution* — "analyze these next 5 VOD games specifically for
  the thing you're working on" — is metered VOD work.

The through-line: **free = description and self-tracking (commodity, ~$0 to serve); paid =
prescription and verified progression over real video (differentiated, genuinely costs money
to produce).** That's a defensible line because it maps exactly onto where cost and
differentiation both actually are.

---

## 7. Prioritized roadmap

Sequenced so the accuracy-first gate is explicit and nothing gamified ships on shaky numbers.

**Phase 0 — Ship and instrument v1 (in progress).**
Finish the v1 core loop (dashboard, 4 scores + confidence tier, one timestamped flag, coach
chat, free Showdown on-ramp, match history/correction). Turn on usage analytics from day one.
QA `showdown_import.py` against several real replays before real beta users. *Exit:* real
users producing real usage data.

**Phase 1 — Accuracy & diagnostic depth (the gate).**
Integrate `accuracy_addons/` into the live tiered pipeline and validate. Build "throw"/
loss-pattern detection (§7 gap). Add opponent-strength-adjusted win rate as a surfaced number.
Add ladder-rating capture + progression for Showdown sources. Confirm skill-score stability
(re-analysis reproducibility). *Exit — this is the Phase 2 gate:* extraction trustworthy,
loss patterns detected, scores stable and opponent-adjusted.

**Phase 2a — Placement & honest progression (lowest-risk gamification).**
Reframe first-N-matches as an explicit **placement assessment**; ship **review-streaks** and
an **XP-style progression currency** (earned by analyzing/reviewing, never by playing). No
population needed for any of these. *Exit:* progression that's motivating and can't be
dishonest.

**Phase 2b — Generated curriculum focus areas.**
Turn coaching flags + skill drivers into a **focus queue** built from the player's own
moments (§5.1). Spaced *attention* re-surfacing of recurring weaknesses. *Exit:* players
have a data-derived "what to work on."

**Phase 2c — Periodic reassessment (the marquee feature).**
Match-count-triggered, opponent-adjusted, confidence-gated before/after that refuses to
over-claim (§5.3). *Exit:* the retention loop — finish focus games → verified improvement.

**Phase 3 — Population features & premium deepening.**
Percentile "you vs. population" once there's a real user base (solves cold-start by *waiting*
for it, not faking it). Deep VOD-metered reassessment as premium. Revisit Bo3/set modeling if
usage shows a tournament-heavy audience. Mobile (view + chat + notifications). *Exit:*
network-effect features and the mature paid tier.

**Deliberately still deferred throughout:** coach/team/streamer features, opponent scouting,
external meta scraping, hearts/lives mechanics, weekly promotion/demotion ladders, a
hand-authored content bank.

---

## 8. Open questions & risks

- **Cold-start for league/percentile.** Any "you vs. others" mechanic is meaningless until
  there's a real population, and a wrong-feeling percentile early on is worse than none. The
  plan's answer is to *sequence* population features last (Phase 3) and lead with mechanics
  that need no population (placement, review-streaks). Open question: what's the minimum user
  count / matches-per-skill-bucket before a percentile is honest? Unknown until there's data;
  don't guess it live.
- **Reassessment feeling punitive rather than motivating.** "You didn't actually improve" is a
  demotivating message if delivered bluntly, and the whole north star is *not* "review your
  losses." Mitigations: always pair a flat/negative result with the *next* concrete focus and
  a genuine "this is a small sample" caveat; celebrate *process* (you varied your leads) even
  when the *outcome* metric is noisy; never let reassessment read as a verdict. This risk is
  real enough that reassessment copy should be usability-tested before it ships broadly.
- **The trust/accuracy dependency is load-bearing and fragile.** Everything in Phase 2 assumes
  the numbers are right. A single high-profile wrong coaching claim ("fix your Tera timing" in
  a no-Tera format — the exact bug the format-rules work exists to prevent) can break trust
  faster than a hundred correct ones build it, especially given the AI-skepticism climate
  (§2.3). The gate in §5.0 is the mitigation; the risk is treating it as a suggestion.
- **Small-sample honesty vs. the desire to show progress.** There's genuine tension between
  "show the user they're leveling up" (retention) and "don't claim improvement from noise"
  (trust). This document sides with trust every time, but that's a *values* call the product
  should make consciously — an over-eager progress bar is the easy, dishonest, higher-short-
  term-retention path, and it's the one that eventually gets found out.
- **Differentiation durability.** The free replay analyzers are actively developed and
  open-source (VS Recorder). Some of the Tier-B differentiators (throw detection, play-style
  labels) are things a motivated open-source project *could* add. The most durable moats are
  the ones that need real cost/infrastructure: video understanding and opponent-adjusted
  verified reassessment over VOD. Lean the paid product there, not toward stat features an
  extension could replicate for free.
- **Audience split risk.** The brief serves both *competitive* and *aspiring* players. Their
  needs diverge: aspiring players want the placement/curriculum/"how do I get good" scaffolding;
  established competitors want the deep matchup/throw/opponent-scouting depth and may find
  gamification patronizing. The skill-score + confidence-tier frame serves both, but Phase 2
  gamification skews toward the aspiring end — watch the usage data for whether the
  progression layer *helps* or *annoys* the high-skill segment, and consider letting advanced
  users dial it down.
- **Is match-count-triggered reassessment right for low-volume players?** A tournament player
  might play 10 ladder games a week; a casual aspiring player, two. Count-based triggering is
  fairer than time-based but could leave a low-volume player waiting months for a reassessment.
  Possible answer: a hybrid (count-based, with a time-based *nudge* to play more), but that
  needs real usage data to tune — flagged, not solved.

---

## Sources

- VS Recorder — [vsrecorder.app](https://vsrecorder.app/), [GitHub (Pocolip/vs-recorder)](https://github.com/Pocolip/vs-recorder), [Chrome Web Store](https://chromewebstore.google.com/detail/vs-recorder-pok%C3%A9mon-vgc-a/fhmjjmjdcijeblnkkhckffbehppdbpob)
- [Reportworm — VGC team & replay analysis](https://reportworm.com/)
- [Pokékipe — Showdown replay analyzer](https://pokekipe.com/replay)
- [Showdown Tier — Pokémon competitive statistics](https://showdowntier.com/)
- [VGC Replay Analyzer — Chrome Web Store](https://chromewebstore.google.com/detail/vgc-replay-analyzer/ikildimeghigegckdcdjbedfapehdimm)
- [Pikalytics — VGC 2026 Reg M-B](https://www.pikalytics.com/)
- [MunchStats — tools](https://munchstats.com/tools/)
- [Smogon Forums — Pokémon VGC Tracker thread](https://www.smogon.com/forums/threads/pokemon-vgc-tracker.3783996/)
- [Mobalytics — 10 things from Challenger coach profile reviews](https://mobalytics.gg/blog/10-things-you-can-learn-challenger-coach-profile-reviews/)
- [Mobalytics — Trustpilot reviews](https://www.trustpilot.com/review/mobalytics.gg)
- [GameBoostingHub — Mobalytics review 2026](https://gameboostinghub.com/reviews/mobalytics/)
- [Wombo Combo — Blitz.gg overlay review](https://www.wombocombo.gg/blog/game-analytics/blitz-gg-overlay-review)
- [Omnic.AI — Forge](https://forge.omnic.ai/) / [about the Forge](https://omnic.ai/forge.html)
- [Quantic Foundry — Gamers' attitudes toward Gen AI (Dec 2025)](https://quanticfoundry.com/2025/12/18/gen-ai/)
- [Gallup — Gen Z's AI adoption steady, skepticism climbs](https://news.gallup.com/poll/708224/gen-adoption-steady-skepticism-climbs.aspx)
- [Trophy — Duolingo gamification case study](https://trophy.so/blog/duolingo-gamification-case-study)
- [StriveCloud — Duolingo gamification & retention](https://www.strivecloud.io/blog/gamification-examples-boost-user-retention-duolingo)
- [The PM Repo — How Duolingo gamified MAU](https://www.thepmrepo.com/articles/how-duolingo-gamified-monthly-active-users-lessons-in-habit-formation)
- [Duolingo blog — spaced repetition](https://blog.duolingo.com/spaced-repetition-for-learning/)
- [Duolingo blog — placement test improvements](https://blog.duolingo.com/partial-credit-improvements-to-duolingos-placement-test/)
- [Sagepub — Rethinking performance measurement in esports (2026)](https://journals.sagepub.com/doi/10.1177/17479541251378643)
- [MDPI Sports — Factors predicting sport coaches' perceived performance](https://www.mdpi.com/2075-4663/13/3/83)
- [NCBI/PMC — 8-week exercise intervention for e-athletes (RCT)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11790659/)
- [StatPearls (NCBI) — Deliberate practice in medical simulation](https://www.ncbi.nlm.nih.gov/books/NBK554558/)
- [Grading for Growth — research on deliberate practice](https://gradingforgrowth.com/p/what-three-research-articles-on-deliberate)
- [Glickman — The Glicko system (PDF)](https://www.glicko.net/glicko/glicko.pdf)
- [Wikipedia — Glicko rating system](https://en.wikipedia.org/wiki/Glicko_rating_system)
- [McGinnis — The Glicko Rating System: When Confidence Matters](https://mcginniscommawill.com/posts/2025-04-29-glicko1-rating-system/)
