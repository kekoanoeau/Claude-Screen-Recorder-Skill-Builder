from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from csrsb.builder import write as write_skill
from csrsb.ingest import load_desktop_recording
from csrsb.schema import Recording, SkillDraft, Step
from csrsb.translator.claude_client import SecretCheckResult
from csrsb.translator.segment import Segment
from csrsb.translator import BuildOptions, build as run_pipeline


@dataclass
class _FakeClaude:
    """Records the call and returns a hand-built draft.

    Lets the test verify the full compress/segment/redact path runs without
    burning real tokens.
    """

    captured: dict | None = None

    def check_secrets(self, skill_md_text: str) -> SecretCheckResult:
        return SecretCheckResult(verdict="clean", findings=[])

    def synthesize(
        self,
        recording: Recording,
        segments: list[Segment],
        screenshots_root: Path,
    ) -> SkillDraft:
        self.captured = {
            "segment_count": len(segments),
            "event_total": sum(len(s.events) for s in segments),
        }
        return SkillDraft(
            name="open-calculator-and-add",
            description=(
                "Use when the user wants to perform a quick arithmetic calculation. "
                "Opens the desktop Calculator app and types the requested expression."
            ),
            title="Open Calculator and add numbers",
            when_to_use=["The user asks to compute a small sum without opening a terminal"],
            prerequisites=["A desktop with the Calculator app installed"],
            inputs=["The expression to compute (e.g. 2 + 2)"],
            high_level_approach=(
                "Open the system launcher, type 'calculator', press Enter, then click the "
                "digit and operator buttons in the order required for the expression."
            ),
            steps=[
                Step(
                    index=1,
                    title="Open Calculator",
                    goal="Launch the Calculator app",
                    action="Open the system launcher and search for Calculator, then press Enter",
                    expected_result="Calculator window appears",
                    fallback="If launcher search fails, use the Applications menu",
                    screenshot_path="screenshots/1.png",
                    source_event_ids=["evt_0001", "evt_0002", "evt_0003"],
                ),
                Step(
                    index=2,
                    title="Enter the expression",
                    goal="Type the digits and operator",
                    action="Click the buttons for each digit and operator in the input expression",
                    expected_result="The display shows the entered expression",
                    fallback=None,
                    screenshot_path="screenshots/4.png",
                    source_event_ids=["evt_0004", "evt_0005", "evt_0006"],
                ),
                Step(
                    index=3,
                    title="Read the result",
                    goal="Compute and report the answer",
                    action="Click the equals button and read the displayed result",
                    expected_result="The result of the expression is shown",
                    fallback=None,
                    screenshot_path="screenshots/5.png",
                    source_event_ids=["evt_0007"],
                ),
            ],
            success_criteria=["The Calculator displays the correct result"],
            failure_modes=["Launcher search may not find Calculator on minimal installs"],
            surface="desktop",
        )


def test_full_pipeline_produces_valid_skill(calculator_recording_dir: Path, tmp_path: Path) -> None:
    recording = load_desktop_recording(calculator_recording_dir)
    fake = _FakeClaude()
    result = run_pipeline(
        recording,
        recording_dir=calculator_recording_dir,
        options=BuildOptions(client=fake),
    )

    assert fake.captured is not None
    assert fake.captured["segment_count"] >= 1
    assert result.draft.name == "open-calculator-and-add"

    out_dir = tmp_path / "skills"
    skill_dir = write_skill(
        draft=result.draft,
        recording=result.scrubbed,
        recording_dir=calculator_recording_dir,
        redaction_log=result.redaction_log,
        out_dir=out_dir,
    )

    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert skill_md.startswith("---\nname: open-calculator-and-add")
    assert "## Steps" in skill_md
    assert "Open Calculator" in skill_md

    redactions = (skill_dir / "reference" / "REDACTIONS.md").read_text(encoding="utf-8")
    assert "_No redactions were applied._" in redactions

    assert (skill_dir / "reference" / "original_recording.json").exists()


def test_redacted_email_propagates_to_log(calculator_recording_dir: Path, tmp_path: Path) -> None:
    recording = load_desktop_recording(calculator_recording_dir)
    # Sneak an email into a typed-text event so the redactor catches it.
    recording.events[1] = recording.events[1].model_copy(
        update={"value": "calculator alice@example.com"}
    )
    fake = _FakeClaude()
    result = run_pipeline(
        recording,
        recording_dir=calculator_recording_dir,
        options=BuildOptions(client=fake),
    )
    assert any(r.kind == "EMAIL" for r in result.redaction_log.redactions)
    assert "alice@example.com" not in result.scrubbed.model_dump_json()
