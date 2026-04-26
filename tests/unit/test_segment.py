from __future__ import annotations

from csrsb.schema import Event, Target
from csrsb.translator.segment import score_boundary, segment


def _evt(idx: int, ts_ms: int, **kwargs) -> Event:
    target = kwargs.pop("target", None)
    if target is None:
        target = Target(url=kwargs.pop("url", None))
    return Event(
        id=f"evt_{idx:04d}",
        ts_ms=ts_ms,
        surface=kwargs.pop("surface", "browser"),
        type=kwargs.pop("type", "click"),
        target=target,
        value=kwargs.pop("value", None),
    )


def test_navigation_creates_a_strong_boundary() -> None:
    a = _evt(1, 0, type="click", target=Target(url="https://a.test"))
    b = _evt(2, 100, type="navigate", target=Target(url="https://b.test"))
    score = score_boundary(a, b)
    assert score.weight >= 3
    assert "navigate" in score.reasons


def test_url_change_without_explicit_navigate_event() -> None:
    a = _evt(1, 0, type="click", target=Target(url="https://a.test"))
    b = _evt(2, 100, type="click", target=Target(url="https://b.test"))
    score = score_boundary(a, b)
    assert "url_change" in score.reasons


def test_temporal_gap_alone_is_below_threshold() -> None:
    # Verb stays the same so only the gap signal fires — should be 2, not enough
    # to cut at the default threshold of 3.
    a = _evt(1, 0, type="click", target=Target(url="https://a.test"))
    b = _evt(2, 5000, type="click", target=Target(url="https://a.test"))
    score = score_boundary(a, b)
    assert score.weight == 2


def test_enter_after_input_cuts() -> None:
    a = _evt(1, 0, type="input", value="hello", target=Target(url="https://a.test"))
    b = _evt(
        2,
        200,
        type="key",
        value={"key": "enter"},
        target=Target(url="https://a.test"),
    )
    score = score_boundary(a, b)
    assert "enter_after_input" in score.reasons
    assert score.weight >= 3


def test_segment_groups_until_navigation() -> None:
    events = [
        _evt(1, 0, type="click", target=Target(url="https://a.test")),
        _evt(2, 100, type="input", value="x", target=Target(url="https://a.test")),
        _evt(3, 200, type="navigate", target=Target(url="https://b.test")),
        _evt(4, 300, type="click", target=Target(url="https://b.test")),
    ]
    segs = segment(events)
    assert len(segs) == 2
    assert [e.id for e in segs[0].events] == ["evt_0001", "evt_0002"]
    assert [e.id for e in segs[1].events] == ["evt_0003", "evt_0004"]
