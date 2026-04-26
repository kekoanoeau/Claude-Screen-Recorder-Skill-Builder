"""Anthropic SDK wrapper for skill synthesis.

Phase 1 uses one model — Claude Opus 4.7 — and one prompt: ``synthesize_skill``.
The system prompt is cached so repeated builds during development hit the cache.

Opus 4.7 specifics applied here:
- Adaptive thinking (``thinking={"type": "adaptive"}``); ``budget_tokens`` is removed
- ``output_config.effort = "high"`` for synthesis quality
- No ``temperature`` / ``top_p`` / ``top_k`` (all 400 on Opus 4.7)
- ``output_config.format = json_schema`` to constrain the response shape
- Streaming with ``messages.stream(...).get_final_message()`` to avoid SDK timeouts
  at the higher ``max_tokens`` we need for full skill drafts
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol

from csrsb.schema import Recording, SkillDraft
from csrsb.translator.prompts.synthesize_skill import (
    SKILL_DRAFT_JSON_SCHEMA,
    SYNTHESIZE_SYSTEM_PROMPT,
    build_user_message,
)
from csrsb.translator.segment import Segment

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 16000
DEFAULT_EFFORT = "high"
MAX_SCREENSHOTS = 8  # Cap images sent to Claude — bigger payloads hurt latency more than quality


class ClaudeClient(Protocol):
    """Subset of ``anthropic.Anthropic`` we depend on. Lets tests inject a fake."""

    def synthesize(
        self,
        recording: Recording,
        segments: list[Segment],
        screenshots_root: Path,
    ) -> SkillDraft:
        ...


@dataclass
class _SegmentSummary:
    index: int
    duration_ms: int
    event_count: int
    events: list[dict[str, Any]]
    boundary_screenshot: Optional[str]


class AnthropicClient:
    """Real Anthropic-backed client. Constructed lazily so tests don't need
    ``ANTHROPIC_API_KEY``."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        effort: str = DEFAULT_EFFORT,
        api_key: Optional[str] = None,
    ) -> None:
        import anthropic  # Lazy import — keeps fakes free of the dependency

        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self._model = model
        self._max_tokens = max_tokens
        self._effort = effort

    def synthesize(
        self,
        recording: Recording,
        segments: list[Segment],
        screenshots_root: Path,
    ) -> SkillDraft:
        summaries = _summarize_segments(segments)
        payload = _build_payload(recording, summaries)
        user_blocks = _build_user_content(payload, summaries, screenshots_root)

        with self._client.messages.stream(
            model=self._model,
            max_tokens=self._max_tokens,
            system=[
                {
                    "type": "text",
                    "text": SYNTHESIZE_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_blocks}],
            thinking={"type": "adaptive"},
            output_config={
                "effort": self._effort,
                "format": {
                    "type": "json_schema",
                    "schema": SKILL_DRAFT_JSON_SCHEMA,
                },
            },
        ) as stream:
            final = stream.get_final_message()

        text = next((b.text for b in final.content if b.type == "text"), None)
        if text is None:
            raise RuntimeError("Synthesis returned no text content")
        return SkillDraft.model_validate(
            {**json.loads(text), "surface": recording.surface}
        )


def _summarize_segments(segments: Iterable[Segment]) -> list[_SegmentSummary]:
    out: list[_SegmentSummary] = []
    for seg in segments:
        events = seg.events
        first, last = events[0], events[-1]
        boundary = next(
            (e.screenshot_path for e in reversed(events) if e.screenshot_path),
            None,
        )
        out.append(
            _SegmentSummary(
                index=seg.index,
                duration_ms=last.ts_ms - first.ts_ms,
                event_count=len(events),
                events=[
                    {
                        "id": e.id,
                        "type": e.type,
                        "value": e.value,
                        "target_url": e.target.url,
                        "target_text": e.target.selector_alternatives.text,
                        "target_role": e.target.selector_alternatives.role_name,
                        "screenshot_path": e.screenshot_path,
                    }
                    for e in events
                ],
                boundary_screenshot=boundary,
            )
        )
    return out


def _build_payload(recording: Recording, summaries: list[_SegmentSummary]) -> dict[str, Any]:
    return {
        "surface": recording.surface,
        "metadata": recording.metadata.model_dump(exclude_none=True),
        "user_intent_hint": recording.metadata.user_intent_hint,
        "duration_ms": int(
            (recording.ended_at - recording.started_at).total_seconds() * 1000
        ),
        "annotations": [n.model_dump() for n in recording.notes],
        "segment_count": len(summaries),
        "segments": [
            {
                "index": s.index,
                "duration_ms": s.duration_ms,
                "event_count": s.event_count,
                "events": s.events,
            }
            for s in summaries
        ],
    }


def _build_user_content(
    payload: dict[str, Any],
    summaries: list[_SegmentSummary],
    screenshots_root: Path,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [{"type": "text", "text": build_user_message(json.dumps(payload, indent=2))}]
    seen: set[str] = set()
    image_count = 0
    for summary in summaries:
        if image_count >= MAX_SCREENSHOTS:
            break
        path = summary.boundary_screenshot
        if not path or path in seen:
            continue
        full = screenshots_root / path
        if not full.exists():
            continue
        try:
            data = base64.standard_b64encode(full.read_bytes()).decode("ascii")
        except OSError:
            continue
        blocks.append(
            {
                "type": "text",
                "text": f"Screenshot for segment {summary.index} ({path}):",
            }
        )
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": data,
                },
            }
        )
        seen.add(path)
        image_count += 1
    return blocks
