"""Convert a browser-extension upload payload into a ``Recording``.

The extension already emits the canonical schema shape (see
``recorders/browser-extension/exporter.js``); ``from_payload`` exists so the
server has one entry point that performs renumbering, timestamp coercion, and
schema validation in one place.
"""

from __future__ import annotations

from typing import Any

from csrsb.ingest import normalize
from csrsb.schema import Recording


def from_payload(payload: dict[str, Any]) -> Recording:
    """Validate and normalize a browser payload into a ``Recording``."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    surface = payload.get("surface")
    if surface != "browser":
        raise ValueError(f"expected surface=browser, got {surface!r}")
    raw_events = payload.get("events", [])
    if not isinstance(raw_events, list):
        raise ValueError("payload.events must be an array")

    events = normalize.ensure_surface(raw_events, "browser")
    events = normalize.normalize_timestamps(events)
    events = normalize.renumber_events(events)

    normalized = {**payload, "events": events}
    return Recording.model_validate(normalized)


def from_zip(zip_path: Any) -> Recording:
    """Load a zip-export saved by the extension's exporter.

    The zip layout is ``recording.json`` at the root plus a ``screenshots/``
    directory. Only the JSON is loaded here — image files are referenced by
    ``screenshot_path`` and the translator resolves them against
    ``recording_dir`` later.
    """
    import json
    import zipfile
    from pathlib import Path

    path = Path(zip_path)
    with zipfile.ZipFile(path) as zf:
        with zf.open("recording.json") as f:
            payload = json.loads(f.read().decode("utf-8"))
    return from_payload(payload)
