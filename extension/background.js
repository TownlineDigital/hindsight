// MV3 service worker - the only piece of this extension that talks to your
// VGC Coach Dashboard backend. Holds no battle-reading logic itself (see
// inject.js/content.js for that); its only job is "given a finished
// battle's raw log, upload it as a new job" using the same POST /jobs
// endpoint the dashboard's own "New Gameplay" panel calls, authenticated
// with a long-lived API key (see backend/api_keys.py + auth.py) instead of
// a short-lived dashboard sign-in session, which this extension - running
// on a completely different origin - has no way to read.

const LOG_PREFIX = "[VGC Coach]";
const MAX_REMEMBERED_ROOMS = 100;

async function getSettings() {
  const stored = await chrome.storage.local.get(["baseUrl", "apiKey", "username", "uploadedRooms"]);
  return {
    baseUrl: stored.baseUrl || "",
    apiKey: stored.apiKey || "",
    username: stored.username || "",
    uploadedRooms: stored.uploadedRooms || [],
  };
}

async function markUploaded(roomid) {
  const { uploadedRooms } = await getSettings();
  const next = [...uploadedRooms.filter((r) => r !== roomid), roomid].slice(-MAX_REMEMBERED_ROOMS);
  await chrome.storage.local.set({ uploadedRooms: next });
}

function notify(title, message) {
  chrome.notifications.create({
    type: "basic",
    iconUrl: "icons/icon128.png",
    title,
    message,
  });
}

async function uploadReplay(payload) {
  const settings = await getSettings();

  if (!settings.baseUrl || !settings.apiKey) {
    console.warn(LOG_PREFIX, "battle finished but the extension isn't configured yet - open the popup.");
    notify(
      "VGC Coach - not configured",
      "A battle just finished. Open the extension popup and set your dashboard URL + API key so future replays upload automatically."
    );
    return;
  }

  if (settings.uploadedRooms.includes(payload.roomid)) {
    console.debug(LOG_PREFIX, "already uploaded, skipping:", payload.roomid);
    return;
  }

  // Which side is "you" - the popup's own username field wins if set (the
  // player may want a specific alt-account name), falling back to whatever
  // inject.js read off the live client, and finally "p1" as a last resort
  // (matches backend/main.py POST /jobs's own `player` default).
  const username = settings.username || payload.myUsername || "p1";

  // Wraps the raw log as {"log": "..."} - the exact shape
  // showdown_import.py's extract_log_text already reads directly (path 1,
  // "a straight JSON response... has a top-level log string field") -
  // deliberately the SAME shape the .json replay API returns, so this file
  // is indistinguishable from a real downloaded replay to everything
  // downstream of it.
  const logJson = JSON.stringify({ log: payload.log, format: payload.format, roomid: payload.roomid });
  const blob = new Blob([logJson], { type: "application/json" });

  const form = new FormData();
  form.append("source_type", "showdown");
  form.append("player", username);
  form.append("files", blob, "replay0.json");

  const url = settings.baseUrl.replace(/\/+$/, "") + "/jobs";

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { Authorization: `Bearer ${settings.apiKey}` },
      body: form,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status}${text ? `: ${text.slice(0, 200)}` : ""}`);
    }
    const job = await res.json().catch(() => ({}));
    await markUploaded(payload.roomid);
    console.debug(LOG_PREFIX, "uploaded", payload.roomid, "->", job.job_id || "(job id unknown)");
    notify(
      "Replay uploaded",
      `${payload.format || "Your battle"} was sent to your VGC Coach Dashboard. It'll show up under Gameplay once it finishes processing.`
    );
  } catch (err) {
    console.error(LOG_PREFIX, "upload failed for", payload.roomid, err);
    notify("VGC Coach - upload failed", String((err && err.message) || err).slice(0, 180));
  }
}

chrome.runtime.onMessage.addListener((message, sender) => {
  if (!message) return;

  if (message.type === "battle-finished") {
    uploadReplay(message.payload);
  }

  if (message.type === "manual-upload-request") {
    // Relayed from the popup (which doesn't have direct access to the
    // Showdown tab's content script) - ask that specific tab's content.js
    // to force a re-scan. See content.js/inject.js for the rest of this
    // round trip.
    chrome.tabs.query({ url: "https://play.pokemonshowdown.com/*" }, (tabs) => {
      for (const tab of tabs) {
        chrome.tabs.sendMessage(tab.id, { type: "force-scan" }).catch(() => {});
      }
    });
  }
});
