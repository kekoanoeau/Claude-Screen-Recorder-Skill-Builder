"""Anthropic SDK wrapper for skill synthesis.

Phase 2 runs two passes:

1. **Per-segment labeling** with **Claude Haiku 4.5** — each segment + its
   boundary screenshot becomes a compact ``StepLabel``.
2. **Whole-skill synthesis** with **Claude Opus 4.7** — Opus consumes the
   labels (not the raw events) plus a few representative screenshots, and
   emits the full ``SkillDraft``.

Splitting the work this way keeps Opus's context small and lets us spend
high-effort tokens on the part that benefits most from them — the final
narrative-shaped output.

Model specifics applied:

- Opus 4.7 — adaptive thinking, ``effort="high"``, no sampling params
- Haiku 4.5 — no ``effort`` (errors on Haiku), no thinking; one-shot label call
- ``output_config.format = json_schema`` on both
- ``cache_control: ephemeral`` on each system prompt (separate cache entries
  per prompt — placement matches the prompt-caching skill guidance)
- Streaming with ``messages.stream(...).get_final_message()`` to dodge the
  SDK's HTTP timeout guard at the higher ``max_tokens`` we use for synthesis
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol

from csrsb.schema import Recording, SkillDraft
from csrsb.translator.prompts.label_step import (
    LABEL_SYSTEM_PROMPT,
    STEP_LABEL_JSON_SCHEMA,
    build_user_message as build_label_user_message,
)
from csrsb.translator.prompts.synthesize_skill import (
    SKILL_DRAFT_JSON_SCHEMA,
    SYNTHESIZE_SYSTEM_PROMPT,
    build_user_message,
)
from csrsb.translator.segment import Segment

DEFAULT_SYNTH_MODEL = "claude-opus-4-7"
DEFAULT_LABEL_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 16000
DEFAULT_LABEL_MAX_TOKENS = 1024
DEFAULT_EFFORT = "high"
MAX_SCREENSHOTS = 8  # Cap images sent to Opus — bigger payloads hurt latency more than quality


@dataclass
class StepLabel:
    """Result of the per-segment labeling pass."""

    segment_index: int
    intent: str
    target_description: Optional[str]
    expected_outcome: Optional[str]
    confidence: str


class ClaudeClient(Protocol):
    """Subset we depend on. Lets tests inject a fake."""

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
        synth_model: str = DEFAULT_SYNTH_MODEL,
        label_model: str = DEFAULT_LABEL_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        label_max_tokens: int = DEFAULT_LABEL_MAX_TOKENS,
        effort: str = DEFAULT_EFFORT,
        api_key: Optional[str] = None,
        skip_labeling: bool = False,
    ) -> None:
        import anthropic  # Lazy import — keeps fakes free of the dependency

        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self._synth_model = synth_model
        self._label_model = label_model
        self._max_tokens = max_tokens
        self._label_max_tokens = label_max_tokens
        self._effort = effort
        self._skip_labeling = skip_labeling

    def synthesize(
        self,
        recording: Recording,
        segments: list[Segment],
        screenshots_root: Path,
    ) -> SkillDraft:
        summaries = _summarize_segments(segments)
        labels: list[StepLabel] = []
        if not self._skip_labeling:
            labels = self._label_segments(summaries, screenshots_root)

        payload = _build_payload(recording, summaries, labels)
        user_blocks = _build_user_content(payload, summaries, screenshots_root)

        with self._client.messages.stream(
            model=self._synth_model,
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

    def _label_segments(
        self,
        summaries: list[_SegmentSummary],
        screenshots_root: Path,
    ) -> list[StepLabel]:
        labels: list[StepLabel] = []
        for summary in summaries:
            label = self._label_one_segment(summary, screenshots_root)
            if label is not None:
                labels.append(label)
        return labels

    def _label_one_segment(
        self,
        summary: _SegmentSummary,
        screenshots_root: Path,
    ) -> Optional[StepLabel]:
        segment_payload = {
            "index": summary.index,
            "duration_ms": summary.duration_ms,
            "events": summary.events,
        }
        content: list[dict[str, Any]] = [
            {"type": "text", "text": build_label_user_message(json.dumps(segment_payload))}
        ]
        screenshot = _maybe_image_block(summary.boundary_screenshot, screenshots_root)
        if screenshot is not None:
            content.append(screenshot)

        with self._client.messages.stream(
            model=self._label_model,
            max_tokens=self._label_max_tokens,
            system=[
                {
                    "type": "text",
                    "text": LABEL_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": content}],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": STEP_LABEL_JSON_SCHEMA,
                },
            },
        ) as stream:
            final = stream.get_final_message()

        text = next((b.text for b in final.content if b.type == "text"), None)
        if text is None:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        return StepLabel(
            segment_index=summary.index,
            intent=data["intent"],
            target_description=data.get("target_description"),
            expected_outcome=data.get("expected_outcome"),
            confidence=data.get("confidence", "low"),
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
                        "accessible_name": e.target.accessible_name,
                        "screenshot_path": e.screenshot_path,
                    }
                    for e in events
                ],
                boundary_screenshot=boundary,
            )
        )
    return out


def _build_payload(
    recording: Recording,
    summaries: list[_SegmentSummary],
    labels: list[StepLabel],
) -> dict[str, Any]:
    label_by_index = {l.segment_index: l for l in labels}
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
                "label": (
                    {
                        "intent": label_by_index[s.index].intent,
                        "target_description": label_by_index[s.index].target_description,
                        "expected_outcome": label_by_index[s.index].expected_outcome,
                        "confidence": label_by_index[s.index].confidence,
                    }
                    if s.index in label_by_index
                    else None
                ),
            }
            for s in summaries
        ],
    }


def _build_user_content(
    payload: dict[str, Any],
    summaries: list[_SegmentSummary],
    screenshots_root: Path,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": build_user_message(json.dumps(payload, indent=2))}
    ]
    seen: set[str] = set()
    image_count = 0
    for summary in summaries:
        if image_count >= MAX_SCREENSHOTS:
            break
        path = summary.boundary_screenshot
        if not path or path in seen:
            continue
        block = _maybe_image_block(path, screenshots_root)
        if block is None:
            continue
        blocks.append(
            {"type": "text", "text": f"Screenshot for segment {summary.index} ({path}):"}
        )
        blocks.append(block)
        seen.add(path)
        image_count += 1
    return blocks


def _maybe_image_block(
    relative_path: Optional[str],
    screenshots_root: Path,
) -> Optional[dict[str, Any]]:
    if not relative_path:
        return None
    full = screenshots_root / relative_path
    if not full.exists():
        return None
    try:
        data = base64.standard_b64encode(full.read_bytes()).decode("ascii")
    except OSError:
        return None
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": data},
    }
