"""Install a generated skill into ``~/.claude/skills/`` or ``./.claude/skills/``."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Literal

Scope = Literal["user", "project"]


def target_root(scope: Scope) -> Path:
    if scope == "user":
        return Path.home() / ".claude" / "skills"
    return Path.cwd() / ".claude" / "skills"


def install(skill_dir: Path, *, scope: Scope = "user", overwrite: bool = False) -> Path:
    """Copy ``skill_dir`` into the chosen scope. Returns the installed path.

    Raises ``FileExistsError`` if the destination exists and ``overwrite=False``.
    """
    skill_dir = Path(skill_dir)
    if not (skill_dir / "SKILL.md").exists():
        raise ValueError(f"{skill_dir} does not look like a skill (missing SKILL.md)")

    root = target_root(scope)
    root.mkdir(parents=True, exist_ok=True)
    dest = root / skill_dir.name
    if dest.exists():
        if not overwrite:
            raise FileExistsError(f"Skill already installed at {dest}")
        shutil.rmtree(dest)
    shutil.copytree(skill_dir, dest)
    return dest
