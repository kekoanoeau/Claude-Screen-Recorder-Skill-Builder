"""Low-level capture primitives — pynput listeners + mss screenshots.

Pure I/O: this module knows how to grab a frame and listen for input. Lifecycle
(when to start, when to stop, where to write) is handled in ``session.py``.
"""

from __future__ import annotations

import io
import platform
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class RawEvent:
    """A raw capture event before normalization into the schema."""

    ts_ms: int
    kind: str  # "click" | "scroll" | "key_press" | "key_release"
    payload: dict[str, Any]


def now_ms() -> int:
    return int(time.time() * 1000)


def take_screenshot(out_path: Path) -> tuple[int, int]:
    """Capture the primary monitor to ``out_path`` (PNG). Returns (width, height).

    Returns ``(0, 0)`` if mss is unavailable so the recorder can degrade
    gracefully on environments without a display server.
    """
    try:
        import mss  # type: ignore[import-untyped]
        from PIL import Image
    except Exception:
        return (0, 0)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with mss.mss() as sct:
        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        raw = sct.grab(monitor)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        out_path.write_bytes(buf.getvalue())
        return (raw.size[0], raw.size[1])


class InputListener:
    """Wraps pynput mouse + keyboard listeners.

    Pushes ``RawEvent``s through ``on_event`` from listener threads. The caller
    is responsible for thread-safe consumption.
    """

    def __init__(self, on_event: Callable[[RawEvent], None]) -> None:
        self._on_event = on_event
        self._mouse_listener: Optional[Any] = None
        self._keyboard_listener: Optional[Any] = None
        self._lock = threading.Lock()
        self._stopped = False

    def start(self) -> None:
        from pynput import keyboard, mouse

        def on_click(x: int, y: int, button: Any, pressed: bool) -> None:
            if not pressed:
                return
            self._emit(
                "click",
                {"x": int(x), "y": int(y), "button": str(button).rsplit(".", 1)[-1]},
            )

        def on_scroll(x: int, y: int, dx: int, dy: int) -> None:
            self._emit("scroll", {"x": int(x), "y": int(y), "dx": int(dx), "dy": int(dy)})

        def on_key_press(key: Any) -> None:
            self._emit("key_press", {"key": _key_repr(key)})

        def on_key_release(key: Any) -> None:
            self._emit("key_release", {"key": _key_repr(key)})

        self._mouse_listener = mouse.Listener(on_click=on_click, on_scroll=on_scroll)
        self._keyboard_listener = keyboard.Listener(
            on_press=on_key_press, on_release=on_key_release
        )
        self._mouse_listener.start()
        self._keyboard_listener.start()

    def stop(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
        if self._keyboard_listener is not None:
            self._keyboard_listener.stop()

    def _emit(self, kind: str, payload: dict[str, Any]) -> None:
        with self._lock:
            if self._stopped:
                return
        self._on_event(RawEvent(ts_ms=now_ms(), kind=kind, payload=payload))


def _key_repr(key: Any) -> str:
    """Best-effort string representation for a pynput key.

    ``Key.shift`` -> ``"shift"``, ``KeyCode(char='a')`` -> ``"a"``.
    """
    char = getattr(key, "char", None)
    if char:
        return char
    name = getattr(key, "name", None)
    if name:
        return name
    return str(key).replace("Key.", "")


def detect_os() -> str:
    return f"{platform.system()} {platform.release()}".strip()
