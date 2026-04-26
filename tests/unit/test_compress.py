from __future__ import annotations

from csrsb.schema import Event
from csrsb.translator.compress import compress


def _key(idx: int, key: str) -> Event:
    return Event(
        id=f"evt_{idx:04d}",
        ts_ms=idx * 100,
        surface="desktop",
        type="key",
        value={"key": key, "action": "press"},
    )


def _scroll(idx: int, dy: int) -> Event:
    return Event(
        id=f"evt_{idx:04d}",
        ts_ms=idx * 100,
        surface="desktop",
        type="scroll",
        value={"x": 0, "y": 0, "dx": 0, "dy": dy},
    )


def test_keystrokes_collapse_into_input_event() -> None:
    events = [_key(1, "h"), _key(2, "i"), _key(3, "enter")]
    out = compress(events)
    assert [e.type for e in out] == ["input", "key"]
    assert out[0].value == "hi"
    assert out[1].value["key"] == "enter"


def test_modifiers_are_dropped_but_typed_chars_stay() -> None:
    events = [_key(1, "shift"), _key(2, "A"), _key(3, "ctrl"), _key(4, "b")]
    out = compress(events)
    assert [e.type for e in out] == ["input"]
    assert out[0].value == "Ab"


def test_consecutive_scrolls_coalesce() -> None:
    events = [_scroll(1, -3), _scroll(2, -5), _scroll(3, -7)]
    out = compress(events)
    assert len(out) == 1
    assert out[0].value["dy"] == -7
