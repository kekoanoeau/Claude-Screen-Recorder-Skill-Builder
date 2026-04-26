"""Orchestrate compress -> segment -> redact -> synthesize -> secret-check.

The pipeline is deliberately small — each stage is a pure function so the
whole thing is easy to test with a fake Claude client.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Optional

from jinja2 import Environment

from csrsb.schema import Recording, SkillDraft
from csrsb.translator.claude_client import AnthropicClient, ClaudeClient
from csrsb.translator.compress import compress
from csrsb.translator.redact import RedactionLog, scrub
from csrsb.translator.segment import segment


@dataclass
class BuildOptions:
    """User-facing knobs for ``build()``. All optional with sensible defaults."""

    allow_pii: bool = False
    gap_ms: int = 1500
    max_segments: int = 25
    skip_secret_check: bool = False
    client: Optional[ClaudeClient] = None  # Overridable for tests


@dataclass
class BuildResult:
    draft: SkillDraft
    redaction_log: RedactionLog
    scrubbed: Recording


def build(
    recording: Recording,
    *,
    recording_dir: Path,
    options: Optional[BuildOptions] = None,
) -> BuildResult:
    """Run the full pipeline.

    ``recording_dir`` is the directory the recording was loaded from — we resolve
    relative ``screenshot_path``s against it when sending images to Claude.
    """
    options = options or BuildOptions()

    scrubbed, log = scrub(recording)

    compressed = compress(scrubbed.events)
    segments = segment(
        compressed,
        gap_ms=options.gap_ms,
        max_segments=options.max_segments,
    )
    if not segments:
        raise ValueError("Recording has no events to translate")

    client: ClaudeClient = options.client or AnthropicClient()
    draft = client.synthesize(scrubbed, segments, recording_dir)

    if not options.skip_secret_check:
        rendered = _preview_skill_md(draft)
        result = client.check_secrets(rendered)
        log.secret_check_verdict = result.verdict
        log.secret_findings = list(result.findings)
        if result.verdict == "needs_review" and result.findings and not options.allow_pii:
            raise SecretsDetectedError(result.findings)

    return BuildResult(draft=draft, redaction_log=log, scrubbed=scrubbed)


class SecretsDetectedError(Exception):
    """Raised when the post-LLM secret-check pass flags real findings.

    Message lists every match so the user can either fix the recording or
    re-run with ``--allow-pii``. The findings are also written to
    ``REDACTIONS.md`` so the user has a durable record after they decide.
    """

    def __init__(self, findings) -> None:  # type: ignore[no-untyped-def]
        self.findings = findings
        summary = "; ".join(f"{f.kind}: {f.reason}" for f in findings)
        super().__init__(
            f"post-LLM secret check found {len(findings)} potential leak(s): {summary}"
        )


def _preview_skill_md(draft: SkillDraft) -> str:
    """Render SKILL.md just enough to feed the secret-check pass.

    Mirrors the production template (``builder.write``) but inlined here so
    the pipeline doesn't take a hard dep on ``builder`` (and so we can run the
    check before deciding whether to write anything to disk).
    """
    template_text = (
        resources.files("csrsb.translator.templates")
        .joinpath("SKILL.md.j2")
        .read_text(encoding="utf-8")
    )
    env = Environment(keep_trailing_newline=True, autoescape=False)
    return env.from_string(template_text).render(draft=draft)
