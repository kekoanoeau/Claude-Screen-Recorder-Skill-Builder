// Content script: capture user interactions in the page.
//
// Runs in every frame (manifest sets all_frames: true). Each frame has its own
// instance; events from sub-frames carry their frame_path back to the
// background service worker so the translator can reconstruct the iframe chain.
//
// We deliberately use *capturing* listeners on the document — the page may
// stopPropagation on its own handlers, but capturing fires before bubbling.

(function () {
  if (window.__csrsbContentLoaded) return;
  window.__csrsbContentLoaded = true;

  const FRAME_PATH = computeFramePath();
  let recording = false;
  let inputDebounce = new WeakMap(); // element -> timeout id, for `input` event coalescing

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg && msg.type === "csrsb.start") {
      recording = true;
      sendResponse({ ok: true });
      return true;
    }
    if (msg && msg.type === "csrsb.stop") {
      recording = false;
      sendResponse({ ok: true });
      return true;
    }
    return false;
  });

  document.addEventListener("click", onClick, true);
  document.addEventListener("input", onInput, true);
  document.addEventListener("change", onChange, true);
  document.addEventListener("submit", onSubmit, true);
  document.addEventListener("keydown", onKeydown, true);
  document.addEventListener("scroll", onScroll, true);

  function onClick(ev) {
    if (!recording) return;
    const target = describeTarget(ev.target);
    emit({
      type: "click",
      target,
      value: { button: ev.button, x: ev.clientX, y: ev.clientY },
    });
  }

  function onInput(ev) {
    if (!recording) return;
    const el = ev.target;
    if (!el || typeof el.value !== "string") return;
    // Skip password and OTP fields entirely — never let their value leave the page.
    if (isSecretField(el)) return;
    // Debounce: emit one event 250ms after the last keystroke per element.
    const prev = inputDebounce.get(el);
    if (prev) clearTimeout(prev);
    const timer = setTimeout(() => {
      inputDebounce.delete(el);
      emit({
        type: "input",
        target: describeTarget(el),
        value: el.value,
      });
    }, 250);
    inputDebounce.set(el, timer);
  }

  function onChange(ev) {
    if (!recording) return;
    const el = ev.target;
    if (!el) return;
    if (isSecretField(el)) return;
    if (el instanceof HTMLInputElement && el.type === "file") {
      const files = Array.from(el.files || []).map((f) => ({
        filename: f.name,
        mime: f.type,
        size: f.size,
      }));
      emit({
        type: "file_upload",
        target: describeTarget(el),
        value: files,
      });
      return;
    }
  }

  function onSubmit(ev) {
    if (!recording) return;
    emit({
      type: "annotation",
      target: describeTarget(ev.target),
      value: { kind: "form_submit" },
    });
  }

  function onKeydown(ev) {
    if (!recording) return;
    // Only emit named/special keys — typed text comes from the `input` event.
    const named = ["Enter", "Tab", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Backspace", "Delete"];
    const isChord = ev.ctrlKey || ev.metaKey || ev.altKey;
    if (!named.includes(ev.key) && !(isChord && ev.key.length === 1)) return;
    if (isSecretField(ev.target)) return;
    emit({
      type: "key",
      target: describeTarget(ev.target),
      value: {
        key: ev.key.toLowerCase(),
        ctrl: ev.ctrlKey,
        shift: ev.shiftKey,
        alt: ev.altKey,
        meta: ev.metaKey,
      },
    });
  }

  let scrollDebounce = null;
  function onScroll(ev) {
    if (!recording) return;
    if (scrollDebounce) clearTimeout(scrollDebounce);
    scrollDebounce = setTimeout(() => {
      scrollDebounce = null;
      emit({
        type: "scroll",
        target: { url: location.href },
        value: { x: window.scrollX, y: window.scrollY },
      });
    }, 200);
  }

  function emit(partial) {
    const event = {
      ts_ms: Date.now(),
      surface: "browser",
      ...partial,
      target: { ...(partial.target || {}), url: location.href, frame_path: FRAME_PATH },
    };
    chrome.runtime.sendMessage({ type: "csrsb.event", event }).catch(() => {
      // Background may be cycling — drop silently rather than throw.
    });
  }

  function isSecretField(el) {
    if (!(el instanceof HTMLElement)) return false;
    if (el instanceof HTMLInputElement) {
      if (el.type === "password") return true;
      const ac = (el.autocomplete || "").toLowerCase();
      if (ac.includes("password") || ac === "one-time-code" || ac.startsWith("cc-")) return true;
    }
    const label = (el.getAttribute("aria-label") || "").toLowerCase();
    if (/password|secret|token|api[ _-]?key|credit[ _-]?card/.test(label)) return true;
    return false;
  }

  function describeTarget(el) {
    if (!(el instanceof Element)) return {};
    const rect = el.getBoundingClientRect();
    return {
      selector_alternatives: rankSelectors(el),
      shadow_path: shadowPath(el),
      viewport_box: {
        x: Math.round(rect.left),
        y: Math.round(rect.top),
        w: Math.round(rect.width),
        h: Math.round(rect.height),
      },
      accessible_name: accessibleName(el),
    };
  }

  function rankSelectors(el) {
    const out = {};
    const testid = el.getAttribute("data-testid") || el.getAttribute("data-test-id");
    if (testid) out.testid = `[data-testid="${cssEscape(testid)}"]`;
    const aria = el.getAttribute("aria-label");
    if (aria) out.aria = `[aria-label="${cssEscape(aria)}"]`;
    const role = el.getAttribute("role") || el.tagName.toLowerCase();
    const name = accessibleName(el);
    if (name) {
      out.role_name = `${role}::${name}`;
      out.text = name;
    }
    out.css = cssPath(el);
    return out;
  }

  function accessibleName(el) {
    const aria = el.getAttribute("aria-label");
    if (aria) return aria.trim().slice(0, 200);
    if (el instanceof HTMLInputElement && el.placeholder) return el.placeholder.trim().slice(0, 200);
    const text = (el.textContent || "").trim();
    return text ? text.slice(0, 200) : null;
  }

  function cssPath(el) {
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && cur !== document.documentElement && parts.length < 8) {
      let part = cur.tagName.toLowerCase();
      if (cur.id) {
        part += `#${cssEscape(cur.id)}`;
        parts.unshift(part);
        break;
      }
      const parent = cur.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter((c) => c.tagName === cur.tagName);
        if (siblings.length > 1) {
          const idx = siblings.indexOf(cur) + 1;
          part += `:nth-of-type(${idx})`;
        }
      }
      parts.unshift(part);
      cur = parent;
    }
    return parts.join(" > ");
  }

  function cssEscape(value) {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return value.replace(/"/g, '\\"');
  }

  function shadowPath(el) {
    const path = [];
    let root = el.getRootNode();
    while (root instanceof ShadowRoot && path.length < 8) {
      const host = root.host;
      if (!host) break;
      path.unshift(cssPath(host));
      root = host.getRootNode();
    }
    return path;
  }

  function computeFramePath() {
    const path = [];
    let frame = window;
    let depth = 0;
    while (frame !== frame.parent && depth < 16) {
      path.unshift(safeFrameURL(frame));
      try {
        frame = frame.parent;
      } catch (_) {
        break;
      }
      depth += 1;
    }
    return path;
  }

  function safeFrameURL(frame) {
    try {
      return frame.location.href;
    } catch (_) {
      return "<cross-origin>";
    }
  }
})();
