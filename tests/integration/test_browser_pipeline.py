"""End-to-end test: load a browser-fixture recording, run the full pipeline
with a fake Claude client, render the skill, validate it.

This exercises the desktop+browser unification — the translator should not
care which surface the recording came from.
"""

from __future__ import annotations

from pathlib import Path

from csrsb.builder import write as write_skill
from csrsb.cli import _validate
from csrsb.schema import Recording, SkillDraft, Step
from csrsb.translator import BuildOptions, build as run_pipeline
from csrsb.translator.segment import Segment


class _FakeClaude:
    def synthesize(
        self,
        recording: Recording,
        segments: list[Segment],
        screenshots_root: Path,
    ) -> SkillDraft:
        return SkillDraft(
            name="download-q1-invoices",
            description=(
                "Use when the user wants to download Q1 invoices for a specific customer "
                "from the example billing portal. Filters the customer list and downloads "
                "the Q1 archive."
            ),
            title="Download Q1 invoices",
            when_to_use=["The user asks to fetch Q1 invoices for a named customer"],
            prerequisites=["An authenticated session in example-billing.test"],
            inputs=["The customer name to filter by"],
            high_level_approach=(
                "Open the invoices page, filter by customer, then click the Q1 download button "
                "and wait for the archive to start downloading."
            ),
            steps=[
                Step(
                    index=1,
                    title="Open the invoices page",
                    goal="Land on the invoice listing for the workspace",
                    action="Navigate to https://example-billing.test/invoices",
                    expected_result="The invoices table renders",
                    fallback=None,
                    screenshot_path=None,
                    source_event_ids=["evt_0001"],
                ),
                Step(
                    index=2,
                    title="Filter by customer",
                    goal="Narrow the table to a single customer's invoices",
                    action="Open the customer filter, type the customer name, then pick the matching option",
                    expected_result="The table shows only the chosen customer's invoices",
                    fallback="If the option doesn't appear, retype with fewer characters",
                    screenshot_path=None,
                    source_event_ids=["evt_0002", "evt_0003", "evt_0004"],
                ),
                Step(
                    index=3,
                    title="Download the Q1 archive",
                    goal="Trigger the Q1 download",
                    action="Click the 'Download Q1' button",
                    expected_result="The browser starts downloading q1.zip",
                    fallback=None,
                    screenshot_path=None,
                    source_event_ids=["evt_0005", "evt_0006"],
                ),
            ],
            success_criteria=["q1.zip is in the user's Downloads folder"],
            failure_modes=["Customer name autocomplete may match the wrong row"],
            surface="browser",
        )


def test_browser_recording_round_trips_to_valid_skill(
    fixtures_root: Path, tmp_path: Path
) -> None:
    rec_dir = fixtures_root / "recordings" / "browser_invoice"
    recording = Recording.from_dir(rec_dir)
    assert recording.surface == "browser"

    result = run_pipeline(
        recording,
        recording_dir=rec_dir,
        options=BuildOptions(client=_FakeClaude()),
    )
    skill_dir = write_skill(
        draft=result.draft,
        recording=result.scrubbed,
        recording_dir=rec_dir,
        redaction_log=result.redaction_log,
        out_dir=tmp_path,
    )

    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "download-q1-invoices" in skill_md
    assert "Surface" in skill_md and "browser" in skill_md
    assert _validate(skill_dir) == []
