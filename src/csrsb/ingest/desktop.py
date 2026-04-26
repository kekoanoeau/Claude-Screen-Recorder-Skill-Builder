"""Load a desktop recording from disk into a ``Recording``."""

from __future__ import annotations

from pathlib import Path

from csrsb.schema import Recording


def load(recording_dir: Path) -> Recording:
    return Recording.from_dir(Path(recording_dir))
