from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_root() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def calculator_recording_dir(fixtures_root: Path) -> Path:
    return fixtures_root / "recordings" / "calculator"
