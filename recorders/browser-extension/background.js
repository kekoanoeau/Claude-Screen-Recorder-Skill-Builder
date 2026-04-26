// Background service worker.
//
// Buffers events from content scripts, captures screenshots via
// chrome.tabs.captureVisibleTab, and bundles everything into the canonical
// recording.json shape on stop.
//
// MV3 service workers are short-lived. We use:
//   1. An offscreen document keepalive while recording — stops the worker
//      from being torn down between events.
//   2. chrome.storage.session for state that must survive a worker restart
//      mid-recording (the event buffer).

const SESSION_STATE_KEY = "csrsb.state";
const SCREENSHOT_THROTTLE_MS = 250;
const DEFAULT_SERVE_URL = "http://127.0.0.1:7778/recordings";

let state = null; // hot copy; mirrors chrome.storage.session for speed

async function loadState() {
  const obj = await chrome.storage.session.get(SESSION_STATE_KEY);
  state = obj[SESSION_STATE_KEY] || null;
  return state;
}

async function saveState() {
  await chrome.storage.session.set({ [SESSION_STATE_KEY]: state });
}

async function ensureOffscreen() {
  // The offscreen document keeps the service worker alive between events.
  if (await chrome.offscreen.hasDocument?.()) return;
  await chrome.offscreen.createDocument({
    url: chrome.runtime.getURL("offscreen.html"),
    reasons: ["BLOBS"],
    justification: "Keep the recorder alive while capturing user actions.",
  });
}

async function closeOffscreen() {
  if (await chrome.offscreen.hasDocument?.()) {
    await chrome.offscreen.closeDocument();
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    if (!state) await loadState();
    try {
      if (msg.type === "csrsb.popup.start") {
        await startRecording(msg);
        sendResponse({ ok: true });
      } else if (msg.type === "csrsb.popup.stop") {
        const result = await stopRecording(msg);
        sendResponse({ ok: true, result });
      } else if (msg.type === "csrsb.popup.status") {
        sendResponse({ recording: !!state, eventCount: state ? state.events.length : 0 });
      } else if (msg.type === "csrsb.popup.note") {
        await addNote(msg.text);
        sendResponse({ ok: true });
      } else if (msg.type === "csrsb.event") {
        await onContentEvent(msg.event, sender);
        sendResponse({ ok: true });
      }
    } catch (err) {
      sendResponse({ ok: false, error: String(err && err.message ? err.message : err) });
    }
  })();
  return true; // keep the sendResponse channel open across awaits
});

chrome.tabs.onUpdated.addListener(async (tabId, info) => {
  if (!state) await loadState();
  if (!state) return;
  if (info.status === "complete" && info.url) {
    state.events.push({
      id: `evt_${state.events.length + 1}`,
      ts_ms: Date.now(),
      surface: "browser",
      type: "navigate",
      target: { url: info.url },
      value: { tab_id: tabId },
    });
    await saveState();
  }
});

chrome.tabs.onCreated.addListener(async (tab) => {
  if (!state) await loadState();
  if (!state) return;
  state.events.push({
    id: `evt_${state.events.length + 1}`,
    ts_ms: Date.now(),
    surface: "browser",
    type: "tab_open",
    target: { url: tab.url || tab.pendingUrl || null },
    value: { tab_id: tab.id },
  });
  await saveState();
});

chrome.tabs.onRemoved.addListener(async (tabId, info) => {
  if (!state) await loadState();
  if (!state) return;
  state.events.push({
    id: `evt_${state.events.length + 1}`,
    ts_ms: Date.now(),
    surface: "browser",
    type: "tab_close",
    target: {},
    value: { tab_id: tabId, window_closing: !!info.isWindowClosing },
  });
  await saveState();
});

chrome.tabs.onActivated.addListener(async (info) => {
  if (!state) await loadState();
  if (!state) return;
  let url = null;
  try {
    const tab = await chrome.tabs.get(info.tabId);
    url = tab.url || null;
  } catch (_) {}
  state.events.push({
    id: `evt_${state.events.length + 1}`,
    ts_ms: Date.now(),
    surface: "browser",
    type: "tab_switch",
    target: { url },
    value: { tab_id: info.tabId, window_id: info.windowId },
  });
  await saveState();
});

async function startRecording(msg) {
  if (state) throw new Error("already recording");
  state = {
    started_at: new Date().toISOString(),
    events: [],
    notes: [],
    metadata: {
      browser: navigator.userAgent,
      user_intent_hint: msg.intent || null,
    },
    last_screenshot_at: 0,
    serve_url: msg.serve_url || DEFAULT_SERVE_URL,
    upload: msg.upload !== false,
  };
  await saveState();
  await ensureOffscreen();
  await broadcastToContentScripts({ type: "csrsb.start" });
}

async function stopRecording(msg) {
  if (!state) throw new Error("not recording");
  await broadcastToContentScripts({ type: "csrsb.stop" });
  await closeOffscreen();

  const recording = {
    version: "1.0",
    surface: "browser",
    started_at: state.started_at,
    ended_at: new Date().toISOString(),
    metadata: {
      ...state.metadata,
      viewport: await currentViewport(),
    },
    events: state.events,
    notes: state.notes,
  };

  let result;
  if (state.upload) {
    result = await uploadRecording(recording, state.serve_url);
  } else {
    result = await downloadRecording(recording);
  }

  state = null;
  await chrome.storage.session.remove(SESSION_STATE_KEY);
  return result;
}

async function addNote(text) {
  if (!state) throw new Error("not recording");
  state.notes.push({ ts_ms: Date.now(), text });
  await saveState();
}

async function onContentEvent(event, sender) {
  if (!state) return;
  // Throttle screenshots: at most one per SCREENSHOT_THROTTLE_MS, only on visual events.
  const visual = ["click", "navigate", "file_upload"].includes(event.type);
  if (visual && Date.now() - state.last_screenshot_at >= SCREENSHOT_THROTTLE_MS) {
    state.last_screenshot_at = Date.now();
    try {
      const tabId = sender && sender.tab ? sender.tab.id : null;
      const dataUrl = await chrome.tabs.captureVisibleTab(
        sender?.tab?.windowId ?? chrome.windows.WINDOW_ID_CURRENT,
        { format: "png" },
      );
      // Strip the "data:image/png;base64," prefix; the server expects raw base64.
      event.screenshot_data = dataUrl.split(",", 2)[1];
    } catch (err) {
      // captureVisibleTab fails on chrome:// URLs and during navigation —
      // proceed without a screenshot.
    }
  }
  event.id = `evt_${state.events.length + 1}`;
  state.events.push(event);
  await saveState();
}

async function broadcastToContentScripts(message) {
  const tabs = await chrome.tabs.query({});
  for (const tab of tabs) {
    if (!tab.id) continue;
    try {
      await chrome.tabs.sendMessage(tab.id, message);
    } catch (_) {
      // No content script in that tab — fine.
    }
  }
}

async function currentViewport() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) return null;
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => ({ w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio || 1 }),
    });
    return result;
  } catch (_) {
    return null;
  }
}

async function uploadRecording(recording, url) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(recording),
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`upload failed (${resp.status}): ${body.slice(0, 200)}`);
  }
  return await resp.json();
}

async function downloadRecording(recording) {
  // No zip support without a third-party lib — just download the JSON. The
  // user can still feed it to `csrsb build` since screenshots are inline as
  // base64 in `screenshot_data`. ``csrsb build`` extracts them on load.
  const blob = new Blob([JSON.stringify(recording, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  await chrome.downloads.download({
    url,
    filename: `csrsb-recording-${Date.now()}.json`,
    saveAs: true,
  });
  return { downloaded: true };
}
