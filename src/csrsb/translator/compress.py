"""Deterministic event compression.

Reduces ~500 raw events down to ~80 by:
- Collapsing consecutive ``key`` press events into a single ``input`` event with
  the typed string.
- Dropping bare modifier-key presses (Shift, Ctrl, Alt, Cmd) — they're already
  reflected in the keystrokes that follow them.
- Dedupe of consecutive identical scrolls within a short window.

The LLM-based segmentation in ``segment.py`` works much better when fed
typed-string ``input`` events instead of raw per-key ``key`` events.
"""

from __future__ import annotations

from typing import Iterable

from csrsb.schema import Event

_MODIFIER_KEYS = {"shift", "ctrl", "alt", "cmd", "meta"}
_NAMED_KEYS_TO_PRESERVE = {
    "enter",
    "tab",
    "backspace",
    "esc",
    "escape",
    "delete",
    "up",
    "down",
    "left",
    "right",
    "home",
    "end",
    "page_up",
    "page_down",
}


def compress(events: Iterable[Event]) -> list[Event]:
    """Return a compressed list of events suitable for segmentation."""
    out: list[Event] = []
    text_buffer: list[str] = []
    text_start_event: Event | None = None

    def flush_text() -> None:
        nonlocal text_buffer, text_start_event
        if text_buffer and text_start_event is not None:
            out.append(
                Event(
                    id=text_start_event.id,
                    ts_ms=text_start_event.ts_ms,
                    surface=text_start_event.surface,
                    type="input",
                    target=text_start_event.target,
                    value="".join(text_buffer),
                    screenshot_path=text_start_event.screenshot_path,
                    viewport=text_start_event.viewport,
                )
            )
        text_buffer = []
        text_start_event = None

    for event in events:
        if event.type == "key" and isinstance(event.value, dict):
            key = str(event.value.get("key", ""))
            action = event.value.get("action", "press")
            if action != "press":
                continue
            canonical = key.lower()
            if canonical in _MODIFIER_KEYS:
                continue
            if len(key) == 1:
                if text_start_event is None:
                    text_start_event = event
                text_buffer.append(key)
                continue
            if canonical in _NAMED_KEYS_TO_PRESERVE:
                flush_text()
                out.append(event)
                continue
            # Unknown named key (e.g. F-keys) — flush typed text and keep the
            # key event so the LLM still sees it.
            flush_text()
            out.append(event)
            continue

        flush_text()
        if event.type == "scroll" and out and out[-1].type == "scroll":
            # Coalesce immediate-successor scrolls — keep the most recent payload
            # to capture the final scroll position.
            out[-1] = event
            continue
        out.append(event)

    flush_text()
    return out
