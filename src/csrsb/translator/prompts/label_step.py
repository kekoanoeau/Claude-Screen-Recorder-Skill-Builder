"""Per-segment labeling prompt (Phase 2).

Haiku 4.5 takes one segment + an optional boundary screenshot and returns a
structured ``StepLabel`` that the synthesis pass aggregates into the final
SKILL.md. Splitting the work this way keeps the synthesis context small —
Opus sees compact labels, not raw event sludge — and lets us run labels in
parallel later if we need throughput.

Haiku 4.5 specifics applied here:
- ``effort`` is not supported on Haiku — omit it (sending it 400s).
- Adaptive thinking is supported, but for short labeling calls we leave it
  off; one-shot summaries don't benefit from extended reasoning.
- ``output_config.format`` enforces the JSON schema below.
"""

from __future__ import annotations

LABEL_SYSTEM_PROMPT = """\
You label one segment of a recorded user workflow.

You receive:
- A short JSON snippet of the segment's events (clicks, typed text, scrolls, navigation)
- Optionally, a screenshot showing the state at the end of the segment

Return a StepLabel JSON object describing what the user appears to be doing in this
segment. Be concise. Phrase the description in terms of intent — "Open the Settings
menu" — not literal mechanics — "Click at x=200 y=300".

Quality rules:

- ``intent`` is one short imperative sentence (≤ 15 words).
- ``target_description`` names the thing being acted on in human terms ("the
  'Save' button in the toolbar", "the customer email field"). If you cannot
  tell, return null.
- ``expected_outcome`` is one sentence describing the visible change you'd
  expect after this segment ("the file save dialog opens"). If unclear,
  return null.
- ``confidence`` is "high" / "medium" / "low" — drop to "low" if the segment
  is ambiguous or the screenshot doesn't help.
"""


def build_user_message(segment_json: str) -> str:
    return (
        "Here is the segment payload (JSON). Return the StepLabel.\n\n"
        f"```json\n{segment_json}\n```"
    )


STEP_LABEL_JSON_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "intent": {"type": "string"},
        "target_description": {"type": ["string", "null"]},
        "expected_outcome": {"type": ["string", "null"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["intent", "target_description", "expected_outcome", "confidence"],
}
