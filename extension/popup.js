// Guided, "just paste the key" flow (reworked 2026-07-09 after direct
// feedback that the original flat-form popup - three required fields, a
// separate Save button, no feedback until a battle actually finished -
// was too much for a non-technical user to feel confident about). This
// version: one visible required field (the API key), a button that jumps
// straight to the dashboard's API-keys panel, and immediate pass/fail
// feedback on Connect - rather than silently "saving" a typo'd key and only
// discovering it's wrong hours later when the first battle fails to upload.
// The dashboard URL and Showdown username are still there for anyone who
// needs them, just tucked under "Advanced settings" since the common case
// (the one deployed dashboard, auto-detected username) needs neither.

const DEFAULT_BASE_URL = "https://vgc-coach-dashboard.onrender.com";

const $getKey = document.getElementById("getKey");
const $apiKey = document.getElementById("apiKey");
const $connect = document.getElementById("connect");
const $baseUrl = document.getElementById("baseUrl");
const $username = document.getElementById("username");
const $checkNow = document.getElementById("checkNow");
const $advanced = document.getElementById("advanced");
const $status = document.getElementById("status");
const $statusText = document.getElementById("statusText");

function setStatus(text, cls) {
  $statusText.textContent = text;
  $status.className = cls || "";
}

function effectiveBaseUrl() {
  return ($baseUrl.value.trim() || DEFAULT_BASE_URL).replace(/\/+$/, "");
}

async function load() {
  const stored = await chrome.storage.local.get(["baseUrl", "apiKey", "username", "uploadedRooms"]);
  $baseUrl.value = stored.baseUrl || "";
  $baseUrl.placeholder = DEFAULT_BASE_URL;
  $apiKey.value = stored.apiKey || "";
  $username.value = stored.username || "";

  if (stored.baseUrl && stored.baseUrl !== DEFAULT_BASE_URL) {
    $advanced.open = true; // surface that a non-default URL is in play, don't hide it silently
  }

  if (stored.apiKey) {
    const count = (stored.uploadedRooms || []).length;
    setStatus(
      `Connected. ${count} replay${count === 1 ? "" : "s"} uploaded so far - just play, nothing else to do.`,
      "ok"
    );
  } else {
    setStatus("Not connected yet - get your key below, then hit Connect.", "warn");
  }
}

$getKey.addEventListener("click", () => {
  const url = `${effectiveBaseUrl()}/dashboard/?tab=network&view=api-keys`;
  chrome.tabs.create({ url });
});

async function requestHostPermission(baseUrl) {
  let origin;
  try {
    origin = new URL(baseUrl).origin + "/*";
  } catch (e) {
    throw new Error("That dashboard URL doesn't look right - check the Advanced settings.");
  }
  const granted = await chrome.permissions.request({ origins: [origin] });
  if (!granted) {
    throw new Error("Permission to reach your dashboard was declined - Connect can't work without it.");
  }
}

async function verifyKey(baseUrl, apiKey) {
  let res;
  try {
    res = await fetch(`${baseUrl}/account/api-keys`, {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
  } catch (e) {
    throw new Error("Couldn't reach that dashboard URL. Check your internet connection, or the URL under Advanced settings.");
  }
  if (res.status === 401) {
    throw new Error("That key doesn't look right - make sure you copied the whole thing, with nothing extra.");
  }
  if (!res.ok) {
    throw new Error(`Dashboard returned an unexpected error (HTTP ${res.status}). Try again in a moment.`);
  }
}

$connect.addEventListener("click", async () => {
  const apiKey = $apiKey.value.trim();
  const baseUrl = effectiveBaseUrl();
  const username = $username.value.trim();

  if (!apiKey) {
    setStatus("Paste your key above first - use \"Get my key\" if you don't have one yet.", "warn");
    return;
  }

  $connect.disabled = true;
  setStatus("Connecting…", "busy");
  try {
    await requestHostPermission(baseUrl);
    await verifyKey(baseUrl, apiKey);
    await chrome.storage.local.set({ baseUrl, apiKey, username });
    setStatus("Connected! Battles will upload automatically from now on.", "ok");
  } catch (e) {
    setStatus(e.message, "bad");
  } finally {
    $connect.disabled = false;
  }
});

$checkNow.addEventListener("click", async () => {
  setStatus("Checking the current Showdown tab for a finished battle…", "busy");
  chrome.runtime.sendMessage({ type: "manual-upload-request" });
  setTimeout(load, 1500);
});

load();
