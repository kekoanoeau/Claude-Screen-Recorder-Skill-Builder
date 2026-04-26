// Intentionally minimal — the document's existence is what keeps the service
// worker resident. We periodically emit a no-op message so the worker has a
// reason to wake up if Chrome paged it out.
setInterval(() => {
  chrome.runtime.sendMessage({ type: "csrsb.keepalive" }).catch(() => {});
}, 25_000);
