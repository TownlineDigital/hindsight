# VGC Coach - Showdown Auto-Upload (browser extension)

Watches battles on `play.pokemonshowdown.com` and automatically uploads the
replay to your VGC Coach Dashboard once each one ends - no manual "save
replay" / "upload" step. Authenticates with a long-lived API key (see the
dashboard's Coaching Network → API keys tab) instead of your normal sign-in,
since a browser extension has no way to read your dashboard session.

This is Phase 1 of the planned Showdown integration - replay auto-upload
only. A live in-battle assistant (real-time advantage score / mistake
flags while you're still playing) is a separate, later phase and isn't
built yet.

## Before you start: the dashboard itself needs the new backend pieces live

This extension talks to endpoints (`/account/api-keys`, the API Keys tab)
that only exist in this session's code - not yet on the deployed dashboard.
Two one-time steps on the dashboard side, done once by whoever runs it
(not something each extension user needs to worry about):

1. `git push` the repo - Render's `autoDeploy: true` rebuilds and
   redeploys both the backend and frontend automatically.
2. Re-run the whole `supabase_schema.sql` file in Supabase's SQL Editor -
   this is a manual step Render's deploy does NOT do for you. Safe to
   re-run in full (every statement is "create/add if not exists"); it just
   adds the new `api_keys` table.

Skip either step and generating a key from the dashboard will fail.

## Install (unpacked, for now - not published to the Chrome Web Store)

1. Open `chrome://extensions` (or the equivalent in any Chromium browser -
   Edge, Brave, etc.).
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked** and select this `extension/` folder itself -
   the one directly containing `manifest.json`, not the `icons` subfolder
   inside it (an easy folder-picker mistake - if you get "Manifest file is
   missing or unreadable," you're one level too deep).
4. The extension's icon should appear in your toolbar.

## Configure

The popup is a two-step flow - most people never need anything beyond this:

1. Click the extension's toolbar icon, then **"Get my key from the
   dashboard →"** - opens your dashboard straight to the API Keys panel in
   a new tab. Click **Generate key** there and copy it (shown once).
2. Back in the popup, paste the key into the box and click **Connect**.
   The popup checks the key against your dashboard right away and tells
   you immediately if it worked - no waiting for a battle to find out.

**Dashboard URL and Showdown username** are tucked under "Advanced
settings" and don't need to be touched for the normal case: the dashboard
URL defaults to `https://vgc-coach-dashboard.onrender.com` (the one real
deployment), and the username is auto-detected from the page. Only open
Advanced settings if you're running the dashboard locally (`http://
localhost:8000`) or auto-detection picks the wrong account.

## Use it

Just play. When a battle you're in ends (win or loss), the extension
uploads it automatically within a few seconds and shows a browser
notification. The replay shows up on your dashboard under **Gameplay**
once the backend finishes processing it (same as any other upload).

If a battle already ended before you configured the extension, or you want
to force a check, open the popup and click **Check current battle now**
while that battle's tab is open.

## How it works

- `inject.js` runs inside the actual Showdown page (not the extension's
  isolated content-script world) so it can read `window.app.rooms[...]
  .battle.stepQueue` - Showdown's own in-memory copy of every `|`-delimited
  protocol line for a battle. When a `|win|`/`|tie|` line shows up, it grabs
  the full log and hands it off.
- `content.js` is the relay between that page-context script and the
  extension proper (MV3 keeps these as separate JS worlds on purpose).
- `background.js` wraps the raw log as `{"log": "..."}` (byte-identical in
  shape to what `showdown_import.py` already parses from a real downloaded
  replay) and `POST`s it to `/jobs` with `source_type=showdown`, the same
  endpoint the dashboard's own "New Gameplay" panel uses.

This deliberately does **not** trigger Showdown's own "Save Replay" upload
flow (which publishes a replay to `replay.pokemonshowdown.com` and requires
the format/room to allow it). Reading `stepQueue` directly works for every
format and never touches Showdown's public replay servers - the log goes
straight from your browser to your own dashboard.

## Known limitation - please read before assuming it's broken

Reading `window.app.rooms[...].battle.stepQueue` depends on Pokemon
Showdown's live client internals. This was verified against public
documentation of Showdown's replay-upload protocol and community-built
tooling that reads the same client state, but **not** against a real,
live two-player battle in this build environment (no way to run an actual
Showdown match from here). If replays aren't uploading:

1. Open DevTools (F12) on the Showdown tab and check the Console for lines
   prefixed `[VGC Coach]`. `inject.js loaded, watching for finished
   battles.` should appear on page load.
2. Play a battle to completion and watch for `battle finished, sending to
   extension: <roomid> <format>`. If that line never appears, Showdown's
   client has likely changed the exact property name this extension reads
   (`app.rooms[...].battle.stepQueue`) - open an issue/report back the
   actual shape of `window.app` in that console and `inject.js`'s
   `findBattleRooms()`/`extractIfFinished()` can be updated to match.
3. If that line DOES appear but nothing shows up on your dashboard, check
   the service worker's own console instead: `chrome://extensions` → this
   extension → **service worker** (under "Inspect views") → look for
   `[VGC Coach]` upload errors there.

## Not built yet

- Chrome Web Store packaging/publishing (load-unpacked only, for now)
- The live in-battle assistant (Phase 2 - real-time advantage score /
  mistake flags while a battle is still in progress, using a JS port of
  `strategic_analysis.py`'s heuristic scorer)
- `optional_host_permissions` covers any dashboard URL you save, but if you
  change the URL later you'll be asked to grant permission again - this is
  expected, not a bug.
