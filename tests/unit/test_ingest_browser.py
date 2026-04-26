from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from csrsb.ingest.browser import from_payload, from_zip
from csrsb.schema import Recording


def test_payload_loads_and_renumbers_events(fixtures_root: Path) -> None:
    raw = json.loads((fixtures_root / "recordings" / "browser_invoice" / "recording.json").read_text())
    # Scramble incoming IDs to confirm renumbering kicks in
    for i, event in enumerate(raw["events"]):
        event["id"] = f"x-{i*7}"
    rec = from_payload(raw)
    assert isinstance(rec, Recording)
    assert rec.surface == "browser"
    assert [e.id for e in rec.events] == [f"evt_{i:04d}" for i in range(1, len(rec.events) + 1)]


def test_payload_rejects_wrong_surface(fixtures_root: Path) -> None:
    raw = json.loads((fixtures_root / "recordings" / "browser_invoice" / "recording.json").read_text())
    raw["surface"] = "desktop"
    with pytest.raises(ValueError, match="surface=browser"):
        from_payload(raw)


def test_zip_export_round_trips(tmp_path: Path, fixtures_root: Path) -> None:
    payload_path = fixtures_root / "recordings" / "browser_invoice" / "recording.json"
    zip_path = tmp_path / "recording.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("recording.json", payload_path.read_text())
    rec = from_zip(zip_path)
    assert rec.surface == "browser"
    assert len(rec.events) > 0
