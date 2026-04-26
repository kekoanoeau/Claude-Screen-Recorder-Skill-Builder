// Popup UI — start/stop a recording, add a note, see status.
//
// Most logic lives in background.js; this file just wires buttons to messages.

const $ = (id) => document.getElementById(id);
const startBtn = $("start");
const stopBtn = $("stop");
const noteBtn = $("add_note");
const statusEl = $("status");

async function refreshStatus() {
  const resp = await chrome.runtime.sendMessage({ type: "csrsb.popup.status" });
  if (resp && resp.recording) {
    startBtn.disabled = true;
    stopBtn.disabled = false;
    noteBtn.disabled = false;
    statusEl.textContent = `recording — ${resp.eventCount} events captured`;
  } else {
    startBtn.disabled = false;
    stopBtn.disabled = true;
    noteBtn.disabled = true;
    statusEl.textContent = "idle";
  }
}

startBtn.addEventListener("click", async () => {
  const intent = $("intent").value.trim();
  const serveUrl = $("serve_url").value.trim();
  const upload = !!serveUrl;
  const resp = await chrome.runtime.sendMessage({
    type: "csrsb.popup.start",
    intent,
    serve_url: serveUrl,
    upload,
  });
  if (resp && resp.ok) {
    statusEl.textContent = "recording — capturing your actions";
    await refreshStatus();
  } else {
    statusEl.textContent = `failed: ${resp && resp.error}`;
  }
});

stopBtn.addEventListener("click", async () => {
  statusEl.textContent = "stopping…";
  const resp = await chrome.runtime.sendMessage({ type: "csrsb.popup.stop" });
  if (resp && resp.ok) {
    if (resp.result && resp.result.path) {
      statusEl.textContent = `uploaded to ${resp.result.path}`;
    } else if (resp.result && resp.result.downloaded) {
      statusEl.textContent = "downloaded recording JSON";
    } else {
      statusEl.textContent = "stopped";
    }
  } else {
    statusEl.textContent = `failed: ${resp && resp.error}`;
  }
  await refreshStatus();
});

noteBtn.addEventListener("click", async () => {
  const text = prompt("Note text:");
  if (!text) return;
  await chrome.runtime.sendMessage({ type: "csrsb.popup.note", text });
  await refreshStatus();
});

document.addEventListener("DOMContentLoaded", refreshStatus);
