"""Multi-signal weighted-vote segmenter (Phase 2).

Each pair of consecutive events is scored against several boundary signals;
the cut fires when the summed weight exceeds ``threshold``. This is robust to
the noise in real recordings — pure temporal gaps over-segment fast typists
and under-segment slow ones.

Signals (weights tuned against the calculator + browser fixtures):

| Signal                                     | Weight |
|--------------------------------------------|--------|
| Navigation (URL change / SPA route)        | 3      |
| Window/app focus change                    | 3      |
| Form submission                            | 3      |
| Enter on focused input                     | 3      |
| ``network_idle`` after ``dom_settled``     | 3      |
| Tab switch / open / close                  | 3      |
| Perceptual-hash distance > threshold       | 2      |
| Temporal gap > 1.5s                        | 2      |
| Verb change (typing → clicking → scrolling)| 1      |

Phase 3 adds the perceptual-hash signal once the desktop recorder learns to
emit ``screen_changed`` events; the framework is in place.
"""

from __future__ import annotations

from dataclasses import dataclass

from csrsb.schema import Event

DEFAULT_THRESHOLD = 3
DEFAULT_GAP_MS = 1500


@dataclass
class Segment:
    """An ordered group of events that the LLM will summarize as one step."""

    index: int
    events: list[Event]


@dataclass
class _BoundaryScore:
    """Per-boundary score, used by tests to assert the heuristic stays sane."""

    weight: int
    reasons: list[str]


def segment(
    events: list[Event],
    *,
    gap_ms: int = DEFAULT_GAP_MS,
    threshold: int = DEFAULT_THRESHOLD,
    max_segments: int = 25,
) -> list[Segment]:
    """Cut ``events`` into segments. Hard-caps at ``max_segments`` by merging
    the smallest neighbours."""
    if not events:
        return []

    groups: list[list[Event]] = [[events[0]]]
    for prev, current in zip(events, events[1:]):
        score = _score_boundary(prev, current, gap_ms=gap_ms)
        if score.weight >= threshold:
            groups.append([current])
        else:
            groups[-1].append(current)

    while len(groups) > max_segments:
        smallest = min(range(1, len(groups)), key=lambda i: len(groups[i]))
        groups[smallest - 1].extend(groups[smallest])
        del groups[smallest]

    return [Segment(index=i, events=g) for i, g in enumerate(groups)]


def score_boundary(prev: Event, current: Event, *, gap_ms: int = DEFAULT_GAP_MS) -> _BoundaryScore:
    """Public-for-tests view of the per-boundary score and its reasons."""
    return _score_boundary(prev, current, gap_ms=gap_ms)


def _score_boundary(prev: Event, current: Event, *, gap_ms: int) -> _BoundaryScore:
    weight = 0
    reasons: list[str] = []

    if current.type == "navigate":
        weight += 3
        reasons.append("navigate")
    elif (
        current.target.url
        and prev.target.url
        and current.target.url != prev.target.url
    ):
        weight += 3
        reasons.append("url_change")

    if current.type in {"focus_change", "tab_open", "tab_close", "tab_switch"}:
        weight += 3
        reasons.append(current.type)

    if current.type == "annotation" and isinstance(current.value, dict) and current.value.get("kind") == "form_submit":
        weight += 3
        reasons.append("form_submit")

    if (
        current.type == "key"
        and isinstance(current.value, dict)
        and str(current.value.get("key", "")).lower() == "enter"
        and prev.type == "input"
    ):
        weight += 3
        reasons.append("enter_after_input")

    if current.type == "network_idle" and prev.type == "dom_settled":
        weight += 3
        reasons.append("network_idle_after_dom_settled")

    if current.type == "screen_changed":
        weight += 2
        reasons.append("screen_changed")

    gap = current.ts_ms - prev.ts_ms
    if gap >= gap_ms:
        weight += 2
        reasons.append(f"gap_{gap}ms")

    if _verb(prev) != _verb(current):
        weight += 1
        reasons.append("verb_change")

    return _BoundaryScore(weight=weight, reasons=reasons)


_VERB_GROUPS = {
    "click": "click",
    "input": "type",
    "key": "type",
    "scroll": "scroll",
    "navigate": "navigate",
    "drag": "drag",
    "drop": "drag",
    "file_upload": "click",
    "annotation": "annotation",
    "hover": "click",
    "focus_change": "navigate",
    "tab_switch": "navigate",
}


def _verb(event: Event) -> str:
    return _VERB_GROUPS.get(event.type, event.type)
