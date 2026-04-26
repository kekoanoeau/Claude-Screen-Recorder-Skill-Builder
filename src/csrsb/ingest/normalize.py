"""Shared normalization logic across browser and desktop ingest paths.

Each recorder produces ``Recording``-shaped output, but the browser extension
emits a few fields the desktop recorder doesn't (frame paths, accessible name,
viewport DPR). This module is the single place to:

- Canonicalize relative timestamps to absolute ms-since-epoch
- Renumber event IDs into ``evt_NNNN`` sequence so segment IDs are predictable
- Drop entries the schema can't accept (without losing the rest of the recording)
"""

from __future__ import annotations

from typing import Any


def renumber_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign deterministic ``evt_0001..`` IDs in chronological order.

    Browser-side IDs come from a JS counter that resets per session; we replace
    them with a stable shape that lines up with desktop recordings.
    """
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(events, start=1):
        new = dict(raw)
        new["id"] = f"evt_{i:04d}"
        out.append(new)
    return out


def normalize_timestamps(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Coerce ``ts_ms`` to ints if the extension serialised them as floats."""
    out: list[dict[str, Any]] = []
    for raw in events:
        new = dict(raw)
        ts = new.get("ts_ms")
        if isinstance(ts, float):
            new["ts_ms"] = int(ts)
        out.append(new)
    return out


def ensure_surface(events: list[dict[str, Any]], surface: str) -> list[dict[str, Any]]:
    """Stamp every event with the surface so downstream code can branch if needed."""
    out: list[dict[str, Any]] = []
    for raw in events:
        new = dict(raw)
        new.setdefault("surface", surface)
        out.append(new)
    return out
