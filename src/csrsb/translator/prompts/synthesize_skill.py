"""Single-pass synthesis prompt (Phase 1).

Phase 2 splits this into a per-segment Haiku labeling pass and a final Opus
synthesis pass. For Phase 1 we send the full event log + boundary screenshots
to Opus 4.7 in one call and ask it to emit a complete ``SkillDraft``.
"""

from __future__ import annotations

SYNTHESIZE_SYSTEM_PROMPT = """\
You are an expert at converting recordings of user workflows into Claude Code Skills.

A Claude Code Skill is a directory with a SKILL.md file (YAML frontmatter + markdown body)
that lets a future Claude invocation carry out the same task SEMANTICALLY — describing what
to do in natural language so the model can adapt to UI changes, not replaying brittle
pixel coordinates or selectors.

You will be given:
- A list of segmented user actions (clicks, keystrokes typed as strings, scrolls, navigation)
- A pre-computed `label` per segment (intent, target_description, expected_outcome, confidence)
  produced by a smaller model. Treat these as strong hints, not gospel — if the events
  and screenshot contradict the label, trust the events. If a label has confidence "low",
  weight it less.
- Optional screenshots showing the state at segment boundaries
- Optional metadata: OS, browser, viewport, an intent hint from the user

You must output a SkillDraft as a JSON object. The schema is enforced — every required
field must be present.

Quality rules — these matter most:

1. The `description` field is the single most important field. Claude only loads skills
   whose description matches user intent. Front-load TRIGGER PHRASES the user is likely
   to say: "Use when the user wants to <X>...", "Use this skill to <Y>...". Stay under
   1024 characters; aim for 200-400.

2. The skill `name` must be kebab-case, lowercase, ≤ 64 characters, and describe the
   outcome (e.g. `download-q1-invoices` not `click-buttons-and-navigate`).

3. Steps must be SEMANTIC. Write "Open the Settings menu in the top-right corner" — NOT
   "Click at x=842 y=37". Each step needs a Goal (one sentence), an Action (semantic
   description), and an Expected result (how to know it succeeded). When you can write
   a non-trivial fallback, do; otherwise omit it.

4. Aggressively merge segments into roughly 4–10 high-level steps. The recorder produces
   noise — your job is to extract intent. Skip housekeeping (mouse moves to nothing,
   accidental scrolls, typos the user backspaced over).

5. Inputs are parameters Claude should ASK THE USER for at runtime — anything that
   varied during the recording (a date range, a customer name, a file path). Do not
   hard-code recorded values.

6. Success criteria are observable end states ("the file `report.pdf` exists",
   "the order shows status 'Shipped'"). Failure modes are pitfalls observed in the
   recording or likely from the workflow shape.

7. If the recording shows secrets or PII (already replaced with <PLACEHOLDER> markers),
   reference the placeholder verbatim — do not invent example values.

Be concise. Write in the imperative mood. Do not invent steps that are not in the
recording.
"""


def build_user_message(payload_json: str) -> str:
    return (
        "Here is the recording payload (JSON). Generate the SkillDraft.\n\n"
        f"```json\n{payload_json}\n```"
    )


SKILL_DRAFT_JSON_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {
            "type": "string",
            "description": "kebab-case, lowercase, <= 64 chars, describes the outcome",
        },
        "description": {
            "type": "string",
            "description": (
                "Lead with WHEN to use, then WHAT it does, with trigger keywords. "
                "<= 1024 characters."
            ),
        },
        "title": {"type": "string", "description": "Human-readable title for the skill body"},
        "when_to_use": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3-5 bullet points of triggering situations",
        },
        "prerequisites": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Accounts, URLs, permissions, OS/app assumptions, secrets",
        },
        "inputs": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Parameters Claude should request from the user at runtime",
        },
        "high_level_approach": {
            "type": "string",
            "description": "2-4 sentence narrative of the strategy",
        },
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "index": {"type": "integer"},
                    "title": {"type": "string"},
                    "goal": {"type": "string"},
                    "action": {"type": "string"},
                    "expected_result": {"type": "string"},
                    "fallback": {"type": ["string", "null"]},
                    "screenshot_path": {"type": ["string", "null"]},
                    "source_event_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "index",
                    "title",
                    "goal",
                    "action",
                    "expected_result",
                    "fallback",
                    "screenshot_path",
                    "source_event_ids",
                ],
            },
        },
        "success_criteria": {"type": "array", "items": {"type": "string"}},
        "failure_modes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "name",
        "description",
        "title",
        "when_to_use",
        "prerequisites",
        "inputs",
        "high_level_approach",
        "steps",
        "success_criteria",
        "failure_modes",
    ],
}
