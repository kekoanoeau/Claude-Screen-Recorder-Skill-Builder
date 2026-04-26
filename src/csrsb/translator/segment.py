"""Naive event segmentation (Phase 1).

Splits a flat event list into ordered groups using two strong signals:

1. URL navigation boundaries (browser surface only)
2. Temporal gaps above ``gap_ms`` (default 1500ms) — interpreted as the user
   pausing to think between distinct subtasks

Phase 3 replaces this with the multi-signal scorer described in the plan
(network_idle, focus_change, perceptual hash, etc.). The interface is
deliberately stable so the swap is local.
"""

from __future__ import annotations

from dataclasses import dataclass

from csrsb.schema import Event


@dataclass
class Segment:
    """An ordered group of events that the LLM will summarize as one step."""

    index: int
    events: list[Event]


def segment(
    events: list[Event],
    *,
    gap_ms: int = 1500,
    max_segments: int = 25,
) -> list[Segment]:
    """Cut ``events`` into segments. Hard-caps at ``max_segments`` by merging
    the smallest neighbours."""
    if not events:
        return []

    groups: list[list[Event]] = [[events[0]]]
    last_url: str | None = events[0].target.url
    for event in events[1:]:
        prev = groups[-1][-1]
        gap = event.ts_ms - prev.ts_ms
        nav = (
            event.type == "navigate"
            or (event.target.url and event.target.url != last_url)
        )
        if gap >= gap_ms or nav:
            groups.append([event])
        else:
            groups[-1].append(event)
        if event.target.url:
            last_url = event.target.url

    while len(groups) > max_segments:
        smallest = min(range(1, len(groups)), key=lambda i: len(groups[i]))
        groups[smallest - 1].extend(groups[smallest])
        del groups[smallest]

    return [Segment(index=i, events=g) for i, g in enumerate(groups)]
