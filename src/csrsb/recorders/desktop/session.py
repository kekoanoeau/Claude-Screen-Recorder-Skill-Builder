"""Desktop recording session — lifecycle, hotkey, manifest writer.

Owns the ``Recording`` being built up, takes a screenshot per click, applies
the configured stop chord, and writes ``recording.json`` + ``screenshots/``
to disk on stop.

Phase 1 captures clicks, scrolls, and keystrokes. Mouse-move noise is dropped.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from csrsb.recorders.desktop.capture import (
    InputListener,
    RawEvent,
    average_hash,
    detect_os,
    frontmost_window,
    hamming_distance,
    now_ms,
    take_screenshot,
)
from csrsb.recorders.desktop.redact import redact_screenshot_file
from csrsb.schema import (
    Annotation,
    Event,
    Recording,
    RecordingMetadata,
    Target,
    Viewport,
)

# Hamming distance over a 64-bit aHash above which we emit a `screen_changed`
# segmentation marker. Tuned empirically — 12 catches new-window / app-switch /
# major layout shifts while ignoring cursor-only deltas.
_SCREEN_CHANGED_HAMMING_THRESHOLD = 12

# How often to poll the OS for focus changes. Cheap enough at 500ms — only one
# extra subprocess call per tick on macOS/Linux.
_FOCUS_POLL_INTERVAL_S = 0.5


@dataclass
class RecorderConfig:
    """User-tunable recorder settings.

    ``stop_chord`` is a set of pynput key names — all must be held to stop. We
    deliberately default to a chord (not a single function key) because F-keys
    are claimed by macOS and many laptops. ``ctrl+shift+esc`` is a safe default
    on every supported OS.
    """

    out_dir: Path
    stop_chord: frozenset[str] = frozenset({"ctrl", "shift", "esc"})
    user_intent_hint: Optional[str] = None
    screenshot_on_click: bool = True
    poll_focus: bool = True
    detect_screen_changes: bool = True
    ocr_redact: bool = False  # Opt-in: requires pytesseract + tesseract binary


@dataclass
class _State:
    """Internal mutable state, guarded by ``DesktopSession._lock``."""

    events: list[Event] = field(default_factory=list)
    notes: list[Annotation] = field(default_factory=list)
    held_keys: set[str] = field(default_factory=set)
    next_event_id: int = 1
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    last_screenshot_size: tuple[int, int] = (0, 0)
    last_screen_hash: Optional[int] = None
    last_focus: Optional[dict] = None  # {app_name, window_title}


class DesktopSession:
    """Drives a single desktop recording from start() until the chord fires."""

    def __init__(self, config: RecorderConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._state = _State()
        self._stop_event = threading.Event()
        self._listener = InputListener(self._on_raw_event)
        self._screenshots_dir = Path(config.out_dir) / "screenshots"
        self._focus_thread: Optional[threading.Thread] = None

    def run(self) -> Path:
        """Start recording and block until the stop chord fires.

        Returns the directory the recording was written to.
        """
        self._screenshots_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._state.started_at = datetime.now(timezone.utc)

        self._listener.start()
        if self.config.poll_focus:
            self._focus_thread = threading.Thread(target=self._focus_loop, daemon=True)
            self._focus_thread.start()
        try:
            self._stop_event.wait()
        finally:
            self._listener.stop()
            if self._focus_thread is not None:
                self._focus_thread.join(timeout=1.0)

        with self._lock:
            self._state.ended_at = datetime.now(timezone.utc)

        return self._write()

    def stop(self) -> None:
        """Stop the session externally (used by tests and the CLI's signal handler)."""
        self._stop_event.set()

    def add_note(self, text: str) -> None:
        """Add a free-text annotation at the current timestamp."""
        with self._lock:
            self._state.notes.append(Annotation(ts_ms=now_ms(), text=text))

    def _on_raw_event(self, raw: RawEvent) -> None:
        """Listener-thread entrypoint — normalize and append to the recording."""
        if raw.kind == "key_press":
            self._handle_key_press(raw)
            return
        if raw.kind == "key_release":
            self._handle_key_release(raw)
            return

        screenshot_rel: Optional[str] = None
        viewport: Optional[Viewport] = None
        if self.config.screenshot_on_click and raw.kind == "click":
            screenshot_rel, viewport = self._capture()

        with self._lock:
            evt_id = f"evt_{self._state.next_event_id:04d}"
            self._state.next_event_id += 1
            target = Target(window_title=None, app_name=None)
            value = raw.payload
            event = Event(
                id=evt_id,
                ts_ms=raw.ts_ms,
                surface="desktop",
                type=raw.kind if raw.kind != "click" else "click",
                target=target,
                value=value,
                screenshot_path=screenshot_rel,
                viewport=viewport,
            )
            self._state.events.append(event)

    def _handle_key_press(self, raw: RawEvent) -> None:
        key = raw.payload["key"]
        with self._lock:
            self._state.held_keys.add(_canonical(key))
            if self.config.stop_chord.issubset(self._state.held_keys):
                self._stop_event.set()
                return
            evt_id = f"evt_{self._state.next_event_id:04d}"
            self._state.next_event_id += 1
            self._state.events.append(
                Event(
                    id=evt_id,
                    ts_ms=raw.ts_ms,
                    surface="desktop",
                    type="key",
                    value={"key": key, "action": "press"},
                )
            )

    def _handle_key_release(self, raw: RawEvent) -> None:
        key = raw.payload["key"]
        with self._lock:
            self._state.held_keys.discard(_canonical(key))

    def _capture(self) -> tuple[Optional[str], Optional[Viewport]]:
        ts = now_ms()
        rel = f"screenshots/{ts}.png"
        out = Path(self.config.out_dir) / rel
        size = take_screenshot(out)
        with self._lock:
            if size != (0, 0):
                self._state.last_screenshot_size = size
            w, h = self._state.last_screenshot_size
        if (w, h) == (0, 0):
            return (None, None)
        # Redact BEFORE the perceptual hash so blurring out a token doesn't
        # then trigger a screen_changed event next time the same screen is
        # captured cleanly.
        if self.config.ocr_redact:
            redact_screenshot_file(out)
        if self.config.detect_screen_changes:
            self._maybe_emit_screen_changed(out, ts)
        return (rel, Viewport(w=w, h=h))

    def _maybe_emit_screen_changed(self, screenshot_path: Path, ts_ms: int) -> None:
        """Compute aHash and, if it differs significantly from the previous frame,
        emit a ``screen_changed`` event so the segmenter has a strong cut signal.
        """
        h = average_hash(screenshot_path)
        if h is None:
            return
        with self._lock:
            prev = self._state.last_screen_hash
            self._state.last_screen_hash = h
            if prev is None:
                return
            if hamming_distance(prev, h) < _SCREEN_CHANGED_HAMMING_THRESHOLD:
                return
            evt_id = f"evt_{self._state.next_event_id:04d}"
            self._state.next_event_id += 1
            self._state.events.append(
                Event(
                    id=evt_id,
                    ts_ms=ts_ms,
                    surface="desktop",
                    type="screen_changed",
                    value={"hamming": hamming_distance(prev, h), "hash": h},
                )
            )

    def _focus_loop(self) -> None:
        """Poll the OS for the focused app and emit ``focus_change`` on transitions.

        Runs on a daemon thread; ``frontmost_window()`` returns ``None`` on
        platforms we don't support, in which case this loop exits cleanly.
        """
        first = frontmost_window()
        if first is None:
            return
        with self._lock:
            self._state.last_focus = first
        while not self._stop_event.wait(_FOCUS_POLL_INTERVAL_S):
            current = frontmost_window()
            if current is None:
                continue
            with self._lock:
                if current == self._state.last_focus:
                    continue
                self._state.last_focus = current
                evt_id = f"evt_{self._state.next_event_id:04d}"
                self._state.next_event_id += 1
                self._state.events.append(
                    Event(
                        id=evt_id,
                        ts_ms=now_ms(),
                        surface="desktop",
                        type="focus_change",
                        target=Target(
                            app_name=current.get("app_name"),
                            window_title=current.get("window_title"),
                        ),
                        value=current,
                    )
                )

    def _write(self) -> Path:
        with self._lock:
            assert self._state.started_at is not None
            assert self._state.ended_at is not None
            recording = Recording(
                surface="desktop",
                started_at=self._state.started_at,
                ended_at=self._state.ended_at,
                metadata=RecordingMetadata(
                    os=detect_os(),
                    user_intent_hint=self.config.user_intent_hint,
                ),
                events=list(self._state.events),
                notes=list(self._state.notes),
            )
        out_dir = Path(self.config.out_dir)
        recording.write_to_dir(out_dir)
        return out_dir


# pynput names mod keys as ``ctrl_l``, ``shift_r``, etc. Map them onto the
# generic chord names users supply (``ctrl``, ``shift``, ``alt``, ``cmd``).
_MOD_ALIASES = {
    "ctrl_l": "ctrl",
    "ctrl_r": "ctrl",
    "shift_l": "shift",
    "shift_r": "shift",
    "alt_l": "alt",
    "alt_r": "alt",
    "alt_gr": "alt",
    "cmd_l": "cmd",
    "cmd_r": "cmd",
    "cmd": "cmd",
}


def _canonical(key: str) -> str:
    return _MOD_ALIASES.get(key, key)
