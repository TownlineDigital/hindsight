// Runs in the PAGE's own JS context (injected as a <script> tag by
// content.js, NOT as a normal MV3 content script) - this is the one file in
// this extension that needs to reach `window.app`, Pokemon Showdown's own
// client-side room manager, which an isolated-world content script cannot
// see directly (MV3 content scripts run in a separate JS world from the
// page by design). content.js relays this file's findings back to the
// extension via window.postMessage, since that's the only channel the two
// worlds share.
//
// WHY THIS READS `battle.stepQueue` INSTEAD OF TRIGGERING SHOWDOWN'S OWN
// "SAVE REPLAY" UPLOAD: Showdown's real replay-save flow (confirmed via
// public documentation/community tooling, not by hand-testing this specific
// extension against a live battle - see extension/README.md's verification
// note) sends `<roomid>|/uploadreplay` over the websocket, waits for a
// `|queryresponse|savereplay|...` reply, then POSTs that payload to
// Showdown's own action.php to publish a PUBLIC replay at
// replay.pokemonshowdown.com. That's more moving parts than this needs, it
// only works if the format/room allows public replays at all, and it
// requires the player to opt in to publishing a replay account holders can
// otherwise conceal. Reading `battle.stepQueue` (the client's own copy of
// every `|`-delimited protocol line for this battle) sidesteps all of that:
// it's already sitting in the page's memory the instant the battle ends,
// works for every format, and never touches Showdown's public replay
// servers at all - the log goes straight from your browser to YOUR OWN
// dashboard. `stepQueue.join('\n')` produces exactly the same `|`-delimited
// text showdown_import.py already parses (see its extract_log_text's
// fallback branch, path 3: "plain log text ... pasted directly" - written
// for a human pasting a log by hand, but byte-for-byte the same shape this
// produces).
(function () {
  const LOG_PREFIX = "[VGC Coach]";
  const SEEN_KEY = "__vgcCoachSeenRooms";
  if (!window[SEEN_KEY]) window[SEEN_KEY] = new Set();

  function findBattleRooms() {
    // `app.rooms` is Showdown client's own live room registry, keyed by
    // room id; a battle room's `.battle` holds the Battle instance whose
    // `.stepQueue` is the running array of raw protocol lines for that
    // battle (confirmed via smogon/pokemon-showdown-client-adjacent
    // community tooling - see README.md). Wrapped defensively: if the
    // client has since renamed/restructured this, this should fail soft
    // (return nothing) rather than throw an error into the page's own
    // console.
    try {
      const app = window.app;
      if (!app || !app.rooms) return [];
      return Object.values(app.rooms).filter(
        (r) => r && r.battle && Array.isArray(r.battle.stepQueue)
      );
    } catch (e) {
      console.debug(LOG_PREFIX, "findBattleRooms() failed - Showdown's client may have changed shape.", e);
      return [];
    }
  }

  function currentUsername() {
    try {
      const app = window.app;
      if (!app || !app.user) return null;
      // Different client versions have exposed the signed-in username as
      // either a Backbone-style `.get('name')` model or a plain `.name`
      // property - try both rather than assuming one.
      if (typeof app.user.get === "function") return app.user.get("name") || null;
      return app.user.name || null;
    } catch (e) {
      return null;
    }
  }

  function extractIfFinished(room, force) {
    const steps = room.battle.stepQueue;
    const hasResult = steps.some(
      (line) => line.startsWith("|win|") || line.startsWith("|tie|")
    );
    if (!hasResult) return null;

    const roomid = room.id || room.battle.id || "unknown-room";
    if (!force && window[SEEN_KEY].has(roomid)) return null;
    window[SEEN_KEY].add(roomid);

    return {
      roomid,
      format: room.battle.tier || room.battle.format || "",
      log: steps.join("\n"),
      myUsername: currentUsername(),
    };
  }

  function scan(force) {
    const rooms = findBattleRooms();
    for (const room of rooms) {
      const payload = extractIfFinished(room, force);
      if (payload) {
        console.debug(LOG_PREFIX, "battle finished, sending to extension:", payload.roomid, payload.format);
        window.postMessage(
          { source: "vgc-coach-extension", type: "battle-finished", payload },
          "*"
        );
      }
    }
  }

  // Polling rather than hooking a specific client event - the exact event
  // name/emitter the current client uses for "battle ended" isn't something
  // this build could verify against a live page (see README.md), and a
  // 3-second poll against an in-memory array is cheap enough not to matter.
  setInterval(() => scan(false), 3000);

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.source !== "vgc-coach-extension" || data.type !== "force-scan") return;
    console.debug(LOG_PREFIX, "manual re-scan requested from popup");
    window[SEEN_KEY].clear();
    scan(true);
  });

  console.debug(LOG_PREFIX, "inject.js loaded, watching for finished battles.");
})();
