"""Verify ``--with-script`` lands a Playwright/pyautogui scaffold next to the skill."""

from __future__ import annotations

from pathlib import Path

from csrsb.builder import write as write_skill
from csrsb.schema import Recording, SkillDraft, Step
from csrsb.translator.claude_client import SecretCheckResult
from csrsb.translator.redact import RedactionLog


def _draft(surface: str) -> SkillDraft:
    return SkillDraft(
        name="example-skill",
        description="Use when example.",
        title="Example",
        when_to_use=["always"],
        prerequisites=[],
        inputs=[],
        high_level_approach="Do the thing.",
        steps=[
            Step(
                index=1,
                title="Do it",
                goal="Do",
                action="Do the thing",
                expected_result="Done",
                fallback=None,
                screenshot_path=None,
                source_event_ids=["evt_0001"],
            )
        ],
        success_criteria=["it is done"],
        failure_modes=[],
        surface=surface,
    )


def test_with_script_writes_replay_for_browser_recording(
    fixtures_root: Path, tmp_path: Path
) -> None:
    rec = Recording.from_dir(fixtures_root / "recordings" / "browser_invoice")
    skill_dir = write_skill(
        draft=_draft("browser"),
        recording=rec,
        recording_dir=fixtures_root / "recordings" / "browser_invoice",
        redaction_log=RedactionLog(),
        out_dir=tmp_path,
        with_script=True,
    )
    replay = (skill_dir / "scripts" / "replay.py").read_text(encoding="utf-8")
    assert "from playwright.sync_api import sync_playwright" in replay
    assert "page.goto(" in replay


def test_without_with_script_leaves_no_scripts_dir(
    calculator_recording_dir: Path, tmp_path: Path
) -> None:
    rec = Recording.from_dir(calculator_recording_dir)
    skill_dir = write_skill(
        draft=_draft("desktop"),
        recording=rec,
        recording_dir=calculator_recording_dir,
        redaction_log=RedactionLog(),
        out_dir=tmp_path,
    )
    assert not (skill_dir / "scripts").exists()
