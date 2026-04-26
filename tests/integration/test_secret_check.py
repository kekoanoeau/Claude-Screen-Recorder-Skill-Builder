"""Pipeline-level test for the post-LLM secret check.

Exercises both the clean and the ``needs_review`` branches without touching
the network — the fake client returns whatever the test seeds it with.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pytest

from csrsb.builder import write as write_skill
from csrsb.schema import Recording, SkillDraft, Step
from csrsb.translator import BuildOptions, build as run_pipeline
from csrsb.translator.claude_client import SecretCheckResult
from csrsb.translator.pipeline import SecretsDetectedError
from csrsb.translator.redact import SecretCheckFinding
from csrsb.translator.segment import Segment


@dataclass
class _FakeClaude:
    secret_result: SecretCheckResult = field(
        default_factory=lambda: SecretCheckResult(verdict="clean", findings=[])
    )

    def check_secrets(self, skill_md_text: str) -> SecretCheckResult:
        return self.secret_result

    def synthesize(self, recording, segments, screenshots_root) -> SkillDraft:
        return SkillDraft(
            name="open-calculator-and-add",
            description="Use when the user wants to do calculator math.",
            title="Calculator",
            when_to_use=["The user wants a sum"],
            prerequisites=[],
            inputs=[],
            high_level_approach="Open Calculator and type the expression.",
            steps=[
                Step(
                    index=1,
                    title="Open",
                    goal="Open Calculator",
                    action="Click the launcher",
                    expected_result="Calculator is foregrounded",
                    fallback=None,
                    screenshot_path=None,
                    source_event_ids=["evt_0001"],
                )
            ],
            success_criteria=["Result is displayed"],
            failure_modes=[],
            surface="desktop",
        )


def test_clean_secret_check_writes_verdict_to_log(
    calculator_recording_dir: Path, tmp_path: Path
) -> None:
    recording = Recording.from_dir(calculator_recording_dir)
    fake = _FakeClaude()
    result = run_pipeline(
        recording,
        recording_dir=calculator_recording_dir,
        options=BuildOptions(client=fake),
    )
    assert result.redaction_log.secret_check_verdict == "clean"
    assert result.redaction_log.secret_findings == []


def test_secret_findings_raise_unless_allow_pii(
    calculator_recording_dir: Path,
) -> None:
    recording = Recording.from_dir(calculator_recording_dir)
    fake = _FakeClaude(
        secret_result=SecretCheckResult(
            verdict="needs_review",
            findings=[
                SecretCheckFinding(
                    matched_text="ghp_FAKE_FOR_TEST",
                    kind="github_pat",
                    reason="GitHub personal access token format",
                )
            ],
        )
    )
    with pytest.raises(SecretsDetectedError) as exc_info:
        run_pipeline(
            recording,
            recording_dir=calculator_recording_dir,
            options=BuildOptions(client=fake),
        )
    assert exc_info.value.findings[0].kind == "github_pat"


def test_allow_pii_demotes_failure_to_warning(
    calculator_recording_dir: Path, tmp_path: Path
) -> None:
    recording = Recording.from_dir(calculator_recording_dir)
    fake = _FakeClaude(
        secret_result=SecretCheckResult(
            verdict="needs_review",
            findings=[
                SecretCheckFinding(
                    matched_text="alice@example.com",
                    kind="email",
                    reason="Looks like a real email address",
                )
            ],
        )
    )
    # allow_pii=True → no exception; findings still land in the log
    result = run_pipeline(
        recording,
        recording_dir=calculator_recording_dir,
        options=BuildOptions(client=fake, allow_pii=True),
    )
    assert result.redaction_log.secret_check_verdict == "needs_review"
    assert any(f.kind == "email" for f in result.redaction_log.secret_findings)


def test_skip_secret_check_leaves_verdict_unset(
    calculator_recording_dir: Path,
) -> None:
    recording = Recording.from_dir(calculator_recording_dir)
    fake = _FakeClaude()
    result = run_pipeline(
        recording,
        recording_dir=calculator_recording_dir,
        options=BuildOptions(client=fake, skip_secret_check=True),
    )
    assert result.redaction_log.secret_check_verdict is None
