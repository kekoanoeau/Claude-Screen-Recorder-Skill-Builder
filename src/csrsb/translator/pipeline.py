"""Orchestrate compress -> segment -> redact -> synthesize.

The pipeline is deliberately small — each stage is a pure function so the
whole thing is easy to test with a fake Claude client.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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
    if log.redactions and not options.allow_pii:
        # Redaction is informational in Phase 1 — the placeholders are already
        # in the payload. The post-LLM secret check (Phase 3) is what will
        # actually fail the build. We log here for the CLI to surface.
        pass

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
    return BuildResult(draft=draft, redaction_log=log, scrubbed=scrubbed)
