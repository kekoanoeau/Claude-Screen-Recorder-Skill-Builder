"""``csrsb`` command-line interface.

Phase 1 commands:

- ``csrsb record``  — start a desktop recording
- ``csrsb build``   — translate a recording into a skill
- ``csrsb install`` — copy a built skill into ``~/.claude/skills/`` or ``./.claude/skills/``
- ``csrsb validate``— lint a built skill (frontmatter, description length, image refs)

The browser-extension receiver (``csrsb serve``) lands in Phase 2.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

import click

from csrsb.builder import write as write_skill
from csrsb.ingest import load_desktop_recording
from csrsb.installer import install as install_skill
from csrsb.recorders.desktop import DesktopSession, RecorderConfig
from csrsb.schema import Recording
from csrsb.server import run as run_server
from csrsb.translator import BuildOptions, build as run_pipeline


@click.group()
@click.version_option(package_name="csrsb")
def main() -> None:
    """Claude Screen Recorder Skill Builder."""


@main.command()
@click.option(
    "--out",
    "out_dir",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
    help="Directory to write the recording into.",
)
@click.option(
    "--stop-chord",
    default="ctrl+shift+esc",
    show_default=True,
    help="Modifier+key chord to stop the recording. Use '+' to combine.",
)
@click.option(
    "--intent",
    "intent",
    default=None,
    help="Free-text hint about what task you're recording (passed to the translator).",
)
@click.option(
    "--no-screenshots",
    is_flag=True,
    default=False,
    help="Skip screenshot capture on click (smaller output, lower-quality skill).",
)
def record(out_dir: Path, stop_chord: str, intent: Optional[str], no_screenshots: bool) -> None:
    """Start a desktop recording. Press the stop chord to finish."""
    chord = frozenset(part.strip().lower() for part in stop_chord.split("+") if part.strip())
    if not chord:
        raise click.BadParameter("--stop-chord must specify at least one key")
    config = RecorderConfig(
        out_dir=out_dir,
        stop_chord=chord,
        user_intent_hint=intent,
        screenshot_on_click=not no_screenshots,
    )
    session = DesktopSession(config)
    click.echo(f"Recording to {out_dir}. Press {' + '.join(sorted(chord))} to stop.")
    written = session.run()
    click.echo(f"Recording saved to {written}")


@main.command()
@click.argument(
    "recording_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--out",
    "out_dir",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
    help="Directory to write the generated skill into.",
)
@click.option(
    "--allow-pii",
    is_flag=True,
    default=False,
    help="Suppress the warning if the redaction sweep matched any patterns.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Replace an existing skill directory.",
)
def build(recording_dir: Path, out_dir: Path, allow_pii: bool, overwrite: bool) -> None:
    """Translate a recording into a Claude Code Skill.

    Auto-detects the surface from the recording itself — desktop and browser
    payloads share the same ``recording.json`` shape after ingest.
    """
    recording = Recording.from_dir(recording_dir)
    result = run_pipeline(
        recording,
        recording_dir=recording_dir,
        options=BuildOptions(allow_pii=allow_pii),
    )

    skill_root = Path(out_dir) / result.draft.name
    if skill_root.exists() and overwrite:
        import shutil

        shutil.rmtree(skill_root)

    skill_dir = write_skill(
        draft=result.draft,
        recording=result.scrubbed,
        recording_dir=recording_dir,
        redaction_log=result.redaction_log,
        out_dir=out_dir,
    )
    click.echo(f"Skill written to {skill_dir}")
    if result.redaction_log.redactions:
        n = len(result.redaction_log.redactions)
        click.echo(
            f"⚠ {n} redaction(s) applied — review {skill_dir / 'reference' / 'REDACTIONS.md'}"
        )


@main.command()
@click.option(
    "--out",
    "out_dir",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
    help="Directory to write incoming recordings into.",
)
@click.option(
    "--port",
    type=int,
    default=7778,
    show_default=True,
    help="Localhost port to listen on. The browser extension defaults to this port.",
)
def serve(out_dir: Path, port: int) -> None:
    """Receive recording uploads from the browser extension.

    Bound to 127.0.0.1 only — the upload contains screenshots that should not
    leave your machine.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    run_server(out_dir, port=port)


@main.command()
@click.argument(
    "skill_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--scope",
    type=click.Choice(["user", "project"]),
    default="user",
    show_default=True,
    help="user → ~/.claude/skills/; project → ./.claude/skills/",
)
@click.option("--overwrite", is_flag=True, default=False, help="Replace if already installed.")
def install(skill_dir: Path, scope: str, overwrite: bool) -> None:
    """Copy a built skill into ``.claude/skills/``."""
    dest = install_skill(skill_dir, scope=scope, overwrite=overwrite)  # type: ignore[arg-type]
    click.echo(f"Installed to {dest}")


@main.command()
@click.argument(
    "skill_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
def validate(skill_dir: Path) -> None:
    """Lint a built skill: SKILL.md frontmatter, description length, image refs."""
    issues = _validate(skill_dir)
    if issues:
        for issue in issues:
            click.echo(f"✗ {issue}")
        sys.exit(1)
    click.echo("✓ Skill looks valid")


def _validate(skill_dir: Path) -> list[str]:
    issues: list[str] = []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return [f"Missing SKILL.md in {skill_dir}"]
    text = skill_md.read_text(encoding="utf-8")
    fm_match = re.match(r"^---\n(.+?)\n---\n", text, re.DOTALL)
    if not fm_match:
        return ["SKILL.md is missing YAML frontmatter"]
    frontmatter = fm_match.group(1)
    name_match = re.search(r"^name:\s*(.+)$", frontmatter, re.MULTILINE)
    desc_match = re.search(r"^description:\s*(.+)$", frontmatter, re.MULTILINE)
    if not name_match:
        issues.append("frontmatter missing `name`")
    elif not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}[a-z0-9]", name_match.group(1).strip()):
        issues.append(f"`name` is not kebab-case or too long: {name_match.group(1).strip()!r}")
    if not desc_match:
        issues.append("frontmatter missing `description`")
    elif len(desc_match.group(1).strip()) > 1024:
        issues.append("`description` exceeds 1024 characters")

    body = text[fm_match.end():]
    for ref in re.findall(r"!\[\]\(([^)]+)\)", body):
        if not (skill_dir / ref).exists():
            issues.append(f"broken image reference: {ref}")
    return issues


if __name__ == "__main__":
    main()
