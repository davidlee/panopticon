// Panopticon Firefox capture — emits raw tab attention events to the
// native messaging host. The host (panopticon-firefox-host) re-stamps
// `source` and re-applies redaction; this script is the producer.
//
// Design notes:
//   * Event page (non-persistent). State lives in `browser.storage.session`
//     and is rehydrated on every emit, so a suspend cycle doesn't lose
//     the active tab.
//   * No segment derivation here — the downstream segmentizer owns that.
//     We only emit raw transitions.
//   * Private windows / incognito tabs are dropped at the source.
//   * URL redaction (strip query+fragment, drop sensitive schemes) is
//     applied here as a first pass; the host re-applies it as belt+braces.

const HOST_NAME = "panopticon_firefox";

const SENSITIVE_SCHEMES = new Set([
  "about:",
  "moz-extension:",
  "chrome:",
  "resource:",
  "view-source:",
  "data:",
  "blob:",
  "javascript:",
  "file:",
]);

const STATE_KEY = "panopticon.state";
const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 30000;
const DWELL_MS = 30000; // seconds before attempting Readability extraction
const MENU_ID = "panopticon-extract";

let port = null;
let reconnectDelay = RECONNECT_MIN_MS;
let connecting = false;
let dwellTimer = null;
let extractedUrls = new Set(); // URLs already extracted this session

function connect() {
  if (port || connecting) return;
  connecting = true;
  try {
    port = browser.runtime.connectNative(HOST_NAME);
    reconnectDelay = RECONNECT_MIN_MS;
    console.log("[panopticon] connected to native host", HOST_NAME);
    port.onDisconnect.addListener(() => {
      const err = port && port.error;
      console.warn("[panopticon] native host disconnected", err);
      port = null;
      scheduleReconnect();
    });
  } catch (e) {
    console.error("[panopticon] connectNative threw", e);
    port = null;
    scheduleReconnect();
  } finally {
    connecting = false;
  }
}

function scheduleReconnect() {
  const delay = reconnectDelay;
  reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS);
  setTimeout(connect, delay);
}

function send(message) {
  if (!port) connect();
  if (!port) {
    console.warn("[panopticon] dropping event, no port", message.event);
    return;
  }
  try {
    port.postMessage(message);
    console.log("[panopticon] sent", message.event, message.url || "");
  } catch (e) {
    console.error("[panopticon] postMessage threw", e);
    port = null;
    scheduleReconnect();
  }
}

function nowIso() {
  // Panopticon convention: local time with explicit UTC offset, millisecond
  // precision — matches Python datetime.isoformat(timespec="milliseconds").
  // The raw store buckets per-day on the *stamped* offset (ts[:10]); emitting
  // UTC `Z` here bucketed browser events on UTC midnight, misaligning them
  // from sway (local-stamped) and tripping the freshness doctor every morning
  // until the offset rolled over. Stamp local so the day matches the producer.
  const d = new Date();
  const p = (n, w = 2) => String(n).padStart(w, "0");
  const off = -d.getTimezoneOffset(); // minutes east of UTC
  const sign = off >= 0 ? "+" : "-";
  const abs = Math.abs(off);
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` +
    `T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}` +
    `.${p(d.getMilliseconds(), 3)}${sign}${p(Math.floor(abs / 60))}:${p(abs % 60)}`
  );
}

function isSensitiveUrl(url) {
  if (!url) return true;
  const lower = url.toLowerCase();
  for (const s of SENSITIVE_SCHEMES) {
    if (lower.startsWith(s)) return true;
  }
  return false;
}

function redact(url) {
  if (isSensitiveUrl(url)) return null;
  try {
    const u = new URL(url);
    if (u.protocol !== "http:" && u.protocol !== "https:") return null;
    u.search = "";
    u.hash = "";
    return { url: u.toString(), domain: u.hostname.toLowerCase() };
  } catch (e) {
    return null;
  }
}

async function loadState() {
  const got = await browser.storage.session.get(STATE_KEY);
  return got[STATE_KEY] || {
    activeWindowId: null,
    activeTabId: null,
    activeUrl: null,
    activeTitle: null,
    audible: false,
  };
}

async function saveState(state) {
  await browser.storage.session.set({ [STATE_KEY]: state });
}

// ── Content extraction (Readability) ───────────────────────────────

function scheduleDwell(tabId, url) {
  clearDwell();
  if (!url || isSensitiveUrl(url)) return;
  if (isUrlExtracted(url)) return;
  dwellTimer = setTimeout(() => {
    injectContentScript(tabId);
  }, DWELL_MS);
}

function clearDwell() {
  if (dwellTimer) {
    clearTimeout(dwellTimer);
    dwellTimer = null;
  }
}

function injectContentScript(tabId) {
  browser.scripting.executeScript({
    target: { tabId },
    files: ["Readability.js", "content.js"],
  }).catch((e) => {
    console.warn("[panopticon] content script injection failed", e.message);
  });
}

function recordExtractedUrl(url) {
  extractedUrls.add(url);
  // Keep the set bounded.
  if (extractedUrls.size > 500) {
    const it = extractedUrls.values();
    for (let i = 0; i < 100; i++) extractedUrls.delete(it.next().value);
  }
}

function isUrlExtracted(url) {
  if (!url) return false;
  // Check both full URL and scheme://host/path stripped version.
  if (extractedUrls.has(url)) return true;
  try {
    const u = new URL(url);
    u.search = "";
    u.hash = "";
    return extractedUrls.has(u.toString());
  } catch (e) {
    return false;
  }
}

browser.runtime.onMessage.addListener((msg) => {
  if (msg.type !== "content_extracted") return;
  const r = redact(msg.url);
  if (!r) return;
  recordExtractedUrl(r.url);

  if (msg.error) {
    send({
      event: "browser_content_extracted",
      ts: nowIso(),
      url: r.url,
      domain: r.domain,
      error: msg.error,
    });
    return;
  }

  send({
    event: "browser_content_extracted",
    ts: nowIso(),
    url: r.url,
    domain: r.domain,
    title: msg.title || null,
    byline: msg.byline || null,
    excerpt: msg.excerpt || null,
    siteName: msg.siteName || null,
    publishedTime: msg.publishedTime || null,
    textContent: msg.textContent || "",
    contentHtml: msg.contentHtml || "",
    length: msg.length || 0,
    capturedAt: msg.capturedAt || nowIso(),
  });
  console.log("[panopticon] content extracted", msg.title || msg.url);
});

async function emitForActiveTab(eventName, tab, extra = {}) {
  if (!tab || tab.incognito) return;
  const r = redact(tab.url);
  if (!r) return;
  send({
    event: eventName,
    ts: nowIso(),
    window_id: tab.windowId,
    tab_id: tab.id,
    url: r.url,
    domain: r.domain,
    title: tab.title || null,
    audible: !!tab.audible,
    muted: !!(tab.mutedInfo && tab.mutedInfo.muted),
    pinned: !!tab.pinned,
    incognito: false,
    status: tab.status || null,
    ...extra,
  });
  await saveState({
    activeWindowId: tab.windowId,
    activeTabId: tab.id,
    activeUrl: r.url,
    activeTitle: tab.title || null,
    audible: !!tab.audible,
  });
}

async function snapshotCurrent() {
  let win;
  try {
    win = await browser.windows.getLastFocused({ populate: false });
  } catch (e) {
    return;
  }
  if (!win || win.incognito || win.focused === false) return;
  const tabs = await browser.tabs.query({ active: true, windowId: win.id });
  if (!tabs.length) return;
  await emitForActiveTab("browser_snapshot", tabs[0]);
}

browser.tabs.onActivated.addListener(async ({ tabId, windowId }) => {
  let tab;
  try {
    tab = await browser.tabs.get(tabId);
  } catch (e) {
    return;
  }
  await emitForActiveTab("browser_tab_active", tab);
  const r = redact(tab.url);
  if (r) scheduleDwell(tab.id, r.url);
});

browser.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (tab.incognito) return;
  if (!tab.active) return;
  const change = {
    title: "title" in changeInfo,
    url: "url" in changeInfo,
    status: "status" in changeInfo,
    audible: "audible" in changeInfo,
  };
  if (!(change.title || change.url || change.status || change.audible)) return;
  await emitForActiveTab("browser_tab_updated", tab, { change });
  if (change.url || change.status === "complete") {
    const r = redact(tab.url);
    if (r) scheduleDwell(tab.id, r.url);
  }
});

browser.webNavigation.onCommitted.addListener(async (details) => {
  if (details.frameId !== 0) return;
  let tab;
  try {
    tab = await browser.tabs.get(details.tabId);
  } catch (e) {
    return;
  }
  if (tab.incognito || !tab.active) return;
  const r = redact(details.url);
  if (!r) return;
  send({
    event: "browser_navigation",
    ts: nowIso(),
    kind: "committed",
    window_id: tab.windowId,
    tab_id: details.tabId,
    frame_id: details.frameId,
    url: r.url,
    domain: r.domain,
    transition_type: details.transitionType || null,
    transition_qualifiers: details.transitionQualifiers || [],
    incognito: false,
  });
});

browser.webNavigation.onHistoryStateUpdated.addListener(async (details) => {
  if (details.frameId !== 0) return;
  let tab;
  try {
    tab = await browser.tabs.get(details.tabId);
  } catch (e) {
    return;
  }
  if (tab.incognito || !tab.active) return;
  const r = redact(details.url);
  if (!r) return;
  send({
    event: "browser_navigation",
    ts: nowIso(),
    kind: "history_state_updated",
    window_id: tab.windowId,
    tab_id: details.tabId,
    frame_id: details.frameId,
    url: r.url,
    domain: r.domain,
    incognito: false,
  });
});

browser.windows.onFocusChanged.addListener(async (windowId) => {
  if (windowId === browser.windows.WINDOW_ID_NONE) {
    clearDwell();
    send({
      event: "browser_window_focus",
      ts: nowIso(),
      window_id: null,
      focused: false,
    });
    return;
  }
  let win;
  try {
    win = await browser.windows.get(windowId);
  } catch (e) {
    return;
  }
  if (win.incognito) return;
  send({
    event: "browser_window_focus",
    ts: nowIso(),
    window_id: windowId,
    focused: true,
  });
  const tabs = await browser.tabs.query({ active: true, windowId });
  if (tabs.length) await emitForActiveTab("browser_tab_active", tabs[0]);
});

try {
  browser.idle.setDetectionInterval(60);
} catch (e) {
  // setDetectionInterval may require the "idle" permission scope already
  // granted; ignore if unavailable.
}

browser.idle.onStateChanged.addListener((state) => {
  if (state === "idle" || state === "locked") clearDwell();
  send({
    event: "browser_idle_state",
    ts: nowIso(),
    state,
  });
});

browser.menus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== MENU_ID) return;
  if (!tab || tab.incognito) return;
  clearDwell();
  injectContentScript(tab.id);
});

console.log("[panopticon] background script loaded");
connect();
snapshotCurrent().catch((e) => console.error("[panopticon] snapshot failed", e));

browser.menus.create({
  id: MENU_ID,
  title: "Extract page content for Panopticon",
  contexts: ["page"],
});
