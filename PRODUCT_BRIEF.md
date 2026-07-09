# Product Brief / Decision Worksheet

A framework to pin down how the web + phone app should work. Each section has a
question, some options, a **recommended default** (my suggestion), and a `► Your call:`
line for you to fill in. Edit freely — the goal is to make YOUR vision explicit so the
frontend build has a target. When it's filled in, hand it to the app-build chat.

---

## 1. North star (one sentence)
What does this app do, for whom, and why do they care?
- Draft: *"Upload your competitive gameplay and get instant, trustworthy analysis and a
  personal AI coach that tells you exactly what to improve."*
► Your call: Upload your competitive gameplay and get instant, trustworthy analysis and
  a personal AI coach — with visible skill progression (scores, streaks, trends) so it
  feels like leveling up, not just reviewing losses. "Duolingo of competitive gaming,"
  but progression is driven by your real match data, not a separate quiz bank.

## 2. Who it's for (rank them)
- **Primary — Competitive players** who want to climb (most volume, price-sensitive).
- Secondary — **Coaches / teams** (higher willingness to pay, per-seat).
- Secondary — **Streamers/creators** (want auto-clips, stats overlays, Patreon value-add).
- *Recommended:* build for the **player** first; design so coach/creator features can bolt on.
► Your call (who is v1 really for?): Competitive players AND aspiring competitive players
  (people learning to get good). Coaches/teams and streamers are deferred — bolt-on later.
  Player-analytics-for-game-designers idea is also deferred (data-strategy note, not a v1
  feature).

## 3. The core loop (the ONE thing users do repeatedly)
Draft flow: **paste a VOD link (or upload) → wait for processing → see their record &
coaching report → ask the AI coach questions → come back after their next session.**
- Key insight: since the engine downloads from a URL server-side, users can just **paste a
  Twitch/YouTube link** — no giant upload needed (huge for mobile).
► Your call (describe the loop in your words): Paste VOD link → processing → dashboard +
  coaching report → chat with AI coach → app surfaces skill scores/streak/progression
  computed FROM the real match data (not a separate quiz system) → come back after the
  next session to see the scores move.

  **DECIDED — Showdown is now explicitly part of this loop, as the free on-ramp:**
  a player can also import Showdown replays (already built, §2a of
  ARCHITECTURE_HANDOFF.md) instead of a VOD — same dashboard/skill-scores/coach-chat
  experience, but instant (no processing wait) and free to serve (no Gemini cost, exact
  parsing not AI-guessed). VOD upload stays the deeper/primary product; Showdown is how
  someone gets their first skill scores at zero cost/friction before ever recording
  gameplay. This also means the "aha" moment (§4) can now happen even faster for a
  Showdown-first user — no processing wait at all.

## 4. The "aha" moment
The single thing that makes a new user go "whoa, I need this."
- Options: (a) the accurate W-L + matchup breakdown they never tracked, (b) the AI coach
  pointing out a specific mistake with a timestamp, (c) "you keep losing to Trick Room."
- *Recommended:* lead with **(b)** — a concrete, timestamped "here's what you did wrong."
► Your call: Combo — the AI coach flags one specific timestamped mistake, AND your first
  skill scores appear (4 starter categories: Tempo, Adaptability, Execution, Closing) with
  a confidence label based on match count (25 = "good understanding," 50 = "strong," 100 =
  "exceptional"). Day one gives both a concrete insight and a number to watch move.

## 5. Screens — WEB (the full experience)
Check/edit what v1 needs:
- [ ] Sign in / account
- [ ] New analysis: paste URL or upload + pick game/format
- [ ] Processing status (progress, est. time/cost)
- [ ] Dashboard: record, win% by lead/bring, matchup matrix, coaching flags
- [ ] Match browser: per-match timeline of events
- [ ] AI coach chat
- [ ] History / trends over time
- [ ] Billing / subscription
► Your call (which are v1 vs later?): v1 nav = 5 screens: (1) Dashboard/home — record,
  4 skill scores + confidence tier, recent coaching flags; (2) New Analysis — paste URL,
  pick game/format; (3) Match History — list → per-match timeline; (4) AI Coach Chat;
  (5) Account — sign in/out, plan placeholder. Trends live on the Dashboard, not a separate
  screen. Billing = placeholder/manual only, not a real payment flow yet.

## 6. Screens — MOBILE (lighter, on-the-go)
Phones are bad at uploading multi-GB video, great at quick viewing + chat + notifications.
- *Recommended mobile v1:* paste-a-link to start analysis, **view the report/dashboard**,
  **chat with the coach**, and **push notification when analysis is done**. Defer heavy
  uploads and deep dashboards to web.
► Your call (what's mobile for?):

## 7. Web vs mobile — what lives where
| Capability | Web | Mobile |
|---|---|---|
| Start analysis by URL | ✅ | ✅ |
| Upload large local video | ✅ | ✕ (or link only) |
| Full dashboard / matchup matrix | ✅ | simplified |
| AI coach chat | ✅ | ✅ (primary) |
| Notifications ("analysis ready") | – | ✅ |
► Your call (adjust the split):

## 8. Feature tiers (ties to pricing)
- **Free:** 1–2 analyses/month, basic record + a coaching tip. (The hook.)
- **Pro (~$10–15/mo):** more analyses, full dashboard, trends, unlimited-ish coach chat.
- **Elite / Coach (~$25–40/mo):** high volume, opponent scouting, team features, priority.
► Your call (what's free vs paid?): Everything free during the POC/beta — no tiers, no
  paywall. Instrument basic usage analytics (which screens/features get used, drop-off
  points) from day one so pricing decisions later are data-driven, not guessed. This is a
  private/beta test before public release, not a monetized public launch.

  **Forward-looking note for when tiers eventually turn on:** now that Showdown import is
  a first-class free on-ramp (§3), it cleanly solves the earlier "unlimited subscription
  loses money" problem (see chat history / hour-based-cost math) — Showdown analyses cost
  ~$0 to serve, so they can stay unlimited-free forever without hurting margin. The future
  paid tier is specifically about VOD analysis volume (the Gemini-cost-heavy path), not
  overall app access. Rough future shape: **unlimited free Showdown import + skill
  tracking; paid tier unlocks VOD upload volume** (hour/credit-based per the earlier cost
  math, not flat-unlimited).

## 9. MVP scope (v1) — be ruthless
The smallest version that delivers the "aha" and is worth paying for.
- *Recommended v1:* **web only**, URL-to-analysis, dashboard (record + coaching flags),
  and the AI coach chat. No mobile, no billing yet (or a simple waitlist/manual pricing).
- Defer: mobile app, deep trends, coach/creator/team features, external meta, batch cost mode.
► Your call (what's in v1? what's explicitly out?): IN: web only, accounts (retain
  structured match/skill data per user), paste-URL VOD analysis, dashboard (record + 4
  skill scores + confidence tier + coaching flags), match history/timeline, AI coach chat.
  OUT (v1): mobile app, quiz/lesson content system, streak/daily-engagement mechanic,
  coach/team/streamer features, real billing (placeholder only), player-analytics-for-
  game-designers product. NOTE: instrument basic usage analytics (event tracking on
  feature/screen usage) from day one — free-for-now, but the point of this POC is to
  gather behavior data to decide what to monetize later.

  **DECIDED — Showdown is IN v1**, explicitly, as the free on-ramp (see §3's update): the
  original "defer to v1.1" call is reversed now that the work turned out to already be
  done and tested. Not just left live by default — actively featured as the free/instant
  way in. One QA caveat before promoting it to real beta testers: `showdown_import.py` has
  only been verified against ONE real public replay so far (`tests/test_showdown_import.py`)
  — worth running it against a handful more real replays first, not a blocker to the
  decision, just due diligence before real users touch it.

## 10. Key open decisions
- One game/format at launch (Champions doubles) or several? *Rec: one, done well.*
- Real-time-ish processing or "we'll email you when it's ready"? *Rec: notify-when-ready.*
- Who hosts the heavy processing — your server/cloud from day one, or a queue on one box? *Rec: one worker box first, fan-out later.*
- Account system now, or link-based results first? *Rec: simple accounts (Supabase/Clerk).*
► Your notes: Accounts = yes, needed to retain each player's structured data (their
  reference + ours). **Built**: real accounts via Supabase/Postgres, with a local-dev-mode
  fallback (no sign-in required, in-memory store) when Supabase isn't configured — so the
  app runs with zero cloud setup and accounts turn on later by filling in `.env`, no code
  change needed. Showdown: **built and already exposed in the UI** — see the MVP-scope
  update in §9; the "source-agnostic schema" design goal is already satisfied in practice,
  not just planned for.
  Batch processing: also built (`--use-batch-api`, ~50% cheaper, not instant) — the
  "who hosts processing" question above is really now "when do we turn batch mode on by
  default," not "should we build it."

## 11. How you'll know it's working (success signals)
- People come back after their *next* gaming session (retention).
- They ask the coach follow-up questions (engagement).
- They'd pay / do pay.
► Your target for v1: TBD — not choosing a primary signal yet. Phase is data collection
  (usage analytics instrumented per §8); the success metric will be picked once there's
  real behavior data to look at.

---

### How to use this
1. Fill in the `► Your call:` lines — even rough answers.
2. The filled-in brief becomes the spec the frontend chat builds against (pairs with
   `ARCHITECTURE_HANDOFF.md`, which is the *backend* spec).
3. Revisit it whenever you're unsure "should I build X?" — if X isn't serving the core
   loop (§3) or the aha (§4), it waits.
