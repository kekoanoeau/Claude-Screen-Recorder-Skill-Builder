"""Post-LLM secret check (Phase 3).

After Opus produces a ``SkillDraft``, Haiku 4.5 reads the rendered draft and
calls out any secrets, credentials, or PII it finds. This is the second line
of defense after the regex sweep in ``redact.py`` — it catches anything we
matched the wrong way (e.g. a token format we don't have a regex for, an
email embedded in a high-entropy string, PII from a screenshot caption that
slipped through).

The model returns a structured list of findings. ``--allow-pii`` on the CLI
turns the resulting failure into a warning; the findings still land in
``REDACTIONS.md`` either way.
"""

from __future__ import annotations

SECRET_CHECK_SYSTEM_PROMPT = """\
You audit a draft Claude Code Skill (SKILL.md) for secrets, credentials, or PII
that should not be checked into source control. The skill was generated from a
recording of someone performing a task; some sensitive values may have leaked
through despite our regex-based scrubber.

You will be given the full SKILL.md text. Return a Findings JSON object listing
every leak you find. Be conservative — false positives cost the user a build
failure they have to override; false negatives ship secrets to disk.

What counts as a finding:
- API keys, OAuth tokens, JWTs, AWS / GCP / Azure credentials, GitHub PATs
- Passwords, password hashes, recovery phrases
- Real email addresses, phone numbers, mailing addresses, government IDs
- Credit card numbers, account numbers, bank routing numbers
- Personal names if combined with another identifier (email, address, etc.)
- Any value that is clearly opaque + high-entropy + 16+ characters

What does NOT count as a finding:
- Placeholder tokens we already redacted (anything matching ``<EMAIL_N>``,
  ``<TOKEN_N>``, ``<PHONE_N>``, etc.)
- Public domain names, public URLs, or example.com / example.org addresses
- Synthetic example values clearly intended as illustration
- Generic words that happen to look like keys (e.g. ``sk-example``)

For each finding, return the matched substring (verbatim from the input), the
kind, and a one-line reason.
"""


def build_user_message(skill_md: str) -> str:
    return (
        "Audit this SKILL.md draft for any secrets / credentials / PII that "
        "leaked through the regex scrubber:\n\n"
        f"```markdown\n{skill_md}\n```"
    )


SECRET_CHECK_JSON_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "matched_text": {"type": "string"},
                    "kind": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["matched_text", "kind", "reason"],
            },
        },
        "verdict": {"type": "string", "enum": ["clean", "needs_review"]},
    },
    "required": ["findings", "verdict"],
}
