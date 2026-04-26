"""Render templates and write a skill directory."""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

from jinja2 import Environment

from csrsb.schema import Recording, SkillDraft
from csrsb.translator.redact import RedactionLog


def _env() -> Environment:
    env = Environment(
        keep_trailing_newline=True,
        trim_blocks=False,
        lstrip_blocks=False,
        autoescape=False,
    )
    return env


def _render(template_name: str, **ctx: object) -> str:
    template_text = (
        resources.files("csrsb.translator.templates").joinpath(template_name).read_text(encoding="utf-8")
    )
    return _env().from_string(template_text).render(**ctx)


def write(
    *,
    draft: SkillDraft,
    recording: Recording,
    recording_dir: Path,
    redaction_log: RedactionLog,
    out_dir: Path,
) -> Path:
    """Write the skill to ``<out_dir>/<draft.name>/``. Returns that path.

    Raises ``FileExistsError`` if the target exists — caller decides whether to
    overwrite.
    """
    skill_dir = Path(out_dir) / draft.name
    if skill_dir.exists():
        raise FileExistsError(f"Skill directory already exists: {skill_dir}")
    reference_dir = skill_dir / "reference"
    reference_dir.mkdir(parents=True)

    skill_md = _render("SKILL.md.j2", draft=draft)
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    redactions_md = _render("REDACTIONS.md.j2", log=redaction_log)
    (reference_dir / "REDACTIONS.md").write_text(redactions_md, encoding="utf-8")

    (reference_dir / "original_recording.json").write_text(
        recording.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )

    src_screens = Path(recording_dir) / "screenshots"
    if src_screens.exists():
        shutil.copytree(src_screens, reference_dir / "screenshots")

    return skill_dir
