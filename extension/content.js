// Runs in the ISOLATED content-script world MV3 gives every content script
// - separate JS globals from the actual page, which is why this file can't
// read `window.app` (Showdown's client) directly and instead injects
// inject.js as a real <script> tag so IT runs in the page's own world (see
// inject.js's own comment for the full "why"). This file is just the
// relay between that injected script and the extension's background
// service worker - it has no battle-reading logic of its own.
(function () {
  const LOG_PREFIX = "[VGC Coach]";

  const script = document.createElement("script");
  script.src = chrome.runtime.getURL("inject.js");
  script.onload = function () {
    this.remove(); // the <script> tag itself is just a delivery mechanism, not needed once it's run
  };
  (document.head || document.documentElement).appendChild(script);

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.source !== "vgc-coach-extension") return;
    if (data.type === "battle-finished") {
      chrome.runtime.sendMessage({ type: "battle-finished", payload: data.payload });
    }
  });

  // The popup's "Check current battle now" button asks the background
  // worker to message this tab, which forwards the request into the page
  // world so inject.js can re-scan immediately (ignoring its own
  // already-uploaded de-dupe for this one manual check) - useful for a
  // battle that finished before the extension had a chance to notice, or
  // one you're only spectating.
  chrome.runtime.onMessage.addListener((message) => {
    if (message && message.type === "force-scan") {
      console.debug(LOG_PREFIX, "relaying force-scan into page context");
      window.postMessage({ source: "vgc-coach-extension", type: "force-scan" }, "*");
    }
  });
})();
