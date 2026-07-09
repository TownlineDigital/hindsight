# V1 Summary — Game Coaching App

## The pitch
Upload your competitive gameplay, get instant AI coaching, and watch skill scores move
over time — "Duolingo of competitive gaming," but progression is computed from your real
matches, not a quiz bank.

## Who it's for
Competitive players and people trying to become competitive. Coaches, teams, streamers,
and a future data product for game designers are all deliberately out — bolt-ons for later.

## The core loop
Paste a VOD link → processing → dashboard with record + coaching report → chat with the
AI coach → skill scores and a confidence label update → come back after the next session
to see them move.

## The aha moment
Day one, two things land at once: the AI coach flags one specific, timestamped mistake,
and your first skill scores appear — Tempo, Adaptability, Execution, Closing — with a
confidence label based on match count (25 = good understanding, 50 = strong, 100 =
exceptional).

## What's IN v1 (web only)
- Accounts (retain each player's structured match/skill data)
- Paste-URL VOD analysis (existing pipeline)
- Dashboard: record, 4 skill scores + confidence tier, coaching flags
- Match History: list → per-match timeline
- AI coach chat
- Basic usage-analytics instrumentation (to inform pricing later — everything is free
  during this phase)

Nav is 5 screens: Dashboard, New Analysis, Match History, Coach Chat, Account.

## What's explicitly OUT
- Mobile app
- Pokémon Showdown integration — real work, deferred to v1.1, but the event schema stays
  source-agnostic so it can plug in later without a rebuild
- Quiz/lesson content system, streaks, daily-engagement mechanics
- Coach/team/streamer features
- Real billing (placeholder only — no paywall in v1)
- Player-analytics-for-game-designers product (data-strategy note, not a screen)

## Open / deferred
- Primary success signal not yet chosen — this phase is data collection; pick the go/no-go
  metric once there's real usage data.
- This is a private/beta POC before public release, not a monetized public launch.

## First 3 things to build
1. **Accounts + data model** — user table, and a structured store for each match's events,
   record, and skill scores (this is the foundation everything else and the future data
   asset depend on).
2. **Backend API wrapping the existing pipeline** — the `POST /jobs`, `GET /jobs/{id}/*`
   contract already sketched in `ARCHITECTURE_HANDOFF.md` §8, so the frontend has something
   real to call.
3. **Dashboard + New Analysis screens** — the core loop end to end (paste link → see
   report + skill scores), since that's what proves or disproves the whole idea.

Full detail is in `poc-starter/PRODUCT_BRIEF.md` (now filled in) and
`poc-starter/ARCHITECTURE_HANDOFF.md` (backend spec).
