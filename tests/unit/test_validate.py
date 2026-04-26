from __future__ import annotations

from pathlib import Path

from csrsb.cli import _validate


def _write_skill(skill_dir: Path, *, name: str = "open-calculator-and-add", description: str = "Use when the user wants to compute a sum in Calculator. Opens Calculator and types the requested expression.") -> None:
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# Title\n\nbody\n",
        encoding="utf-8",
    )


def test_clean_skill_passes(tmp_path: Path) -> None:
    skill = tmp_path / "open-calculator-and-add"
    _write_skill(skill)
    assert _validate(skill) == []


def test_uppercase_name_is_flagged(tmp_path: Path) -> None:
    skill = tmp_path / "BadName"
    _write_skill(skill, name="BadName")
    issues = _validate(skill)
    assert any("kebab-case" in i for i in issues)


def test_long_description_is_flagged(tmp_path: Path) -> None:
    skill = tmp_path / "ok-name"
    _write_skill(skill, description="x" * 1100)
    issues = _validate(skill)
    assert any("1024" in i for i in issues)


def test_broken_image_ref_is_flagged(tmp_path: Path) -> None:
    skill = tmp_path / "ok-name"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: ok-name\ndescription: Use when needed\n---\n\n![](reference/missing.png)\n",
        encoding="utf-8",
    )
    issues = _validate(skill)
    assert any("broken image" in i for i in issues)
