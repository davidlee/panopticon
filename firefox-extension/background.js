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

// Query params that *are* a page's identity, kept through redaction for
// the listed hosts only; every other param is still stripped. Must equal
// IDENTITY_PARAMS in panopticon/firefox_host/validate.py — a host test
// parses this literal, so keep it strict JSON (ISS-003).
const IDENTITY_PARAMS = {
  "news.ycombinator.com": ["id"],
  "www.youtube.com": ["v"],
  "youtube.com": ["v"],
  "m.youtube.com": ["v"]
};

// Source of a content extraction, tagged at the call site (SL-010 D3). Must
// equal TRIGGERS in panopticon/firefox_host/validate.py — a host test parses
// this literal, so keep it strict JSON.
const TRIGGERS = ["manual", "dwell"];

const STATE_KEY = "panopticon.state";
const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 30000;
// A connection this long-lived proves the host runs; only then does the
// backoff reset, so a host that dies at start keeps backing off (ISS-004).
const RECONNECT_STABLE_MS = 10000;
const DWELL_MS = 30000; // seconds before attempting Readability extraction
const REPLY_TIMEOUT_MS = 10000; // manual requests are answered or forgotten
const MENU_ID = "panopticon-extract";
const NO_REPLY =
  "No reply from Panopticon; the path is still available with `just content-path`";

let port = null;
let reconnectDelay = RECONNECT_MIN_MS;
let connectedAt = 0;
let connecting = false;
let dwellTimer = null;
let extractedUrls = new Set(); // URLs already extracted this session
const pending = new Map(); // manual request id -> reply timeout id (R3)

function connect() {
  if (port || connecting) return;
  connecting = true;
  try {
    port = browser.runtime.connectNative(HOST_NAME);
    connectedAt = Date.now();
    port.onMessage.addListener(onHostMessage);
    port.onDisconnect.addListener(() => {
      const err = port && port.error;
      console.warn("[panopticon] native host disconnected", err);
      port = null;
      if (Date.now() - connectedAt >= RECONNECT_STABLE_MS) {
        reconnectDelay = RECONNECT_MIN_MS;
      }
      // Every manual request still awaiting a reply ends here, exactly once
      // (D10): drop its timer and say so.
      for (const id of [...pending.keys()]) {
        cancelPending(id);
        notify(NO_REPLY);
      }
      scheduleReconnect();
    });
    console.log("[panopticon] connected to native host", HOST_NAME);
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

// Returns false when the message could not be posted (no port, or the port
// threw); callers that owe the user a notification need to know.
function send(message) {
  if (!port) connect();
  if (!port) {
    console.warn("[panopticon] dropping event, no port", message.event);
    return false;
  }
  try {
    port.postMessage(message);
    console.log("[panopticon] sent", message.event, message.url || "");
    return true;
  } catch (e) {
    console.error("[panopticon] postMessage threw", e);
    port = null;
    scheduleReconnect();
    return false;
  }
}

// Fixed text only — never the path, URL or page title (SL-010 EX-2):
// notification centres mirror to lock screens.
function notify(message) {
  try {
    browser.notifications
      .create({
        type: "basic",
        iconUrl: "icons/icon-48.png",
        title: "Panopticon",
        message,
      })
      .catch((e) => console.warn("[panopticon] notification failed", e.message));
  } catch (e) {
    console.warn("[panopticon] notification threw", e.message);
  }
}

function cancelPending(id) {
  // Returns false when the request was already settled (reply, timeout or
  // disconnect) — that one has had its single notification.
  const timer = pending.get(id);
  if (timer === undefined) return false;
  clearTimeout(timer);
  pending.delete(id);
  return true;
}

// Host → extension replies (design §5.2). Dispatch on `type`; anything else
// is a kind this version doesn't know (IDE-003 adds more) and is ignored.
async function onHostMessage(msg) {
  if (!msg || msg.type !== "content_path") {
    console.debug("[panopticon] ignoring host message", msg && msg.type);
    return;
  }
  if (!cancelPending(msg.id)) return; // unknown or already settled
  if (!msg.ok) {
    notify(`Capture failed: ${msg.reason}`);
    return;
  }
  try {
    await navigator.clipboard.writeText(msg.path);
    notify("Markdown path copied to clipboard");
  } catch (e) {
    // R1: the write can be refused (focus, compositor). Say what happened.
    console.warn("[panopticon] clipboard write failed", e.message);
    notify("Page captured; copying the path failed");
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

function identityQuery(host, params) {
  const keep = IDENTITY_PARAMS[host] || [];
  const pairs = [...params].filter(([k]) => keep.includes(k)).sort();
  return new URLSearchParams(pairs).toString();
}

function redact(url) {
  if (isSensitiveUrl(url)) return null;
  try {
    const u = new URL(url);
    if (u.protocol !== "http:" && u.protocol !== "https:") return null;
    u.search = identityQuery(u.hostname, u.searchParams);
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
    extract(tabId, "dwell");
  }, DWELL_MS);
}

function clearDwell() {
  if (dwellTimer) {
    clearTimeout(dwellTimer);
    dwellTimer = null;
  }
}

// Inject, then call panopticonExtract() and await its value: the article comes
// back to this call, so the trigger is known from the call site and two
// extractions on one tab can't be confused (D3).
async function extract(tabId, trigger) {
  const manual = trigger === "manual";
  let article;
  try {
    await browser.scripting.executeScript({
      target: { tabId },
      files: ["Readability.js", "content.js"],
    });
    const [frame] = await browser.scripting.executeScript({
      target: { tabId },
      func: () => panopticonExtract(),
    });
    article = (frame && frame.result) || { error: "extraction_returned_nothing" };
  } catch (e) {
    console.warn("[panopticon] content extraction failed", e.message);
    if (manual) notify("Capture failed: the page could not be read");
    return;
  }

  const r = redact(article.url);
  if (!r) {
    console.warn("[panopticon] content extraction dropped, unsupported url");
    if (manual) notify("Capture failed: unsupported page");
    return;
  }
  recordExtractedUrl(r.url);

  // One payload, one send site; trigger (and for manual the correlation id)
  // spread in below.
  const payload = {
    event: "browser_content_extracted",
    ts: nowIso(),
    url: r.url,
    domain: r.domain,
    trigger,
  };
  if (article.error) {
    payload.error = article.error;
  } else {
    payload.title = article.title || null;
    payload.byline = article.byline || null;
    payload.excerpt = article.excerpt || null;
    payload.siteName = article.siteName || null;
    payload.publishedTime = article.publishedTime || null;
    payload.textContent = article.textContent || "";
    payload.contentHtml = article.contentHtml || "";
    payload.length = article.length || 0;
    console.log("[panopticon] content extracted", trigger, article.title || r.url);
  }

  if (manual) {
    const id = crypto.randomUUID();
    payload.id = id;
    // Register before sending: the reply can land before send() returns (D10).
    pending.set(
      id,
      setTimeout(() => {
        if (cancelPending(id)) notify(NO_REPLY);
      }, REPLY_TIMEOUT_MS),
    );
    if (!send(payload) && cancelPending(id)) {
      notify("Capture failed: not connected to the native host");
    }
    return;
  }
  send(payload);
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
  // Recorded URLs are redacted; compare like with like.
  const r = redact(url);
  return r !== null && extractedUrls.has(r.url);
}

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
  extract(tab.id, "manual");
});

console.log("[panopticon] background script loaded");
connect();
snapshotCurrent().catch((e) => console.error("[panopticon] snapshot failed", e));

browser.menus.create({
  id: MENU_ID,
  title: "Extract page content for Panopticon",
  contexts: ["page"],
});
