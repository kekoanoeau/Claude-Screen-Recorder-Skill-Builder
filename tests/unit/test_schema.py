from __future__ import annotations

from pathlib import Path

from csrsb.schema import Recording


def test_calculator_fixture_round_trips(calculator_recording_dir: Path, tmp_path: Path) -> None:
    rec = Recording.from_dir(calculator_recording_dir)
    assert rec.surface == "desktop"
    assert len(rec.events) == 7

    out = rec.write_to_dir(tmp_path)
    assert out.exists()
    rec2 = Recording.from_dir(tmp_path)
    assert rec2.model_dump(exclude_none=True) == rec.model_dump(exclude_none=True)
