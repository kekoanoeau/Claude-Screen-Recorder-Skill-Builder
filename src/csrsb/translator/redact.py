"""Phase 1 redaction: regex sweep over event values for obvious secrets and PII.

Replaces matches with typed placeholders (``<EMAIL_1>``, ``<TOKEN_1>``) and
records every redaction in a ``RedactionLog``. The translator also writes a
``REDACTIONS.md`` next to the generated skill so the user can audit before
installing.

Phase 3 layers OCR-based screenshot scrubbing and an LLM-based post-check on
top of this baseline. ``--allow-pii`` on the CLI suppresses the failure when
matches are found but does not skip redaction itself — the placeholders are
still substituted.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from csrsb.schema import Event, Recording

# Patterns are intentionally conservative — false positives are cheap (the user
# sees them in REDACTIONS.md and can re-record), false negatives are not.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("AWS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GITHUB_PAT", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    ("STRIPE_KEY", re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("ANTHROPIC_KEY", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{32,}\b")),
    ("BEARER_TOKEN", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    ("PHONE", re.compile(r"\+?\d{1,3}[\s.\-]?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
]

_HIGH_ENTROPY_THRESHOLD = 3.5
_HIGH_ENTROPY_MIN_LEN = 24


@dataclass
class Redaction:
    event_id: str
    placeholder: str
    kind: str
    original_length: int


@dataclass
class SecretCheckFinding:
    """One leak flagged by the post-LLM secret-check pass.

    Distinct from ``Redaction``: a Redaction is a substitution we *applied*; a
    Finding is a leak we *detected* in the rendered draft. The CLI groups them
    in REDACTIONS.md so the user sees both lists side by side.
    """

    matched_text: str
    kind: str
    reason: str


@dataclass
class RedactionLog:
    redactions: list[Redaction] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)
    secret_findings: list[SecretCheckFinding] = field(default_factory=list)
    secret_check_verdict: Optional[str] = None  # "clean" | "needs_review" | None if skipped

    def next_placeholder(self, kind: str) -> str:
        n = self.counters.get(kind, 0) + 1
        self.counters[kind] = n
        return f"<{kind}_{n}>"


def scrub(recording: Recording) -> tuple[Recording, RedactionLog]:
    """Return a new ``Recording`` with sensitive substrings replaced.

    The original recording is not mutated.
    """
    log = RedactionLog()
    new_events: list[Event] = []
    for event in recording.events:
        new_events.append(_scrub_event(event, log))
    return recording.model_copy(update={"events": new_events}), log


def _scrub_event(event: Event, log: RedactionLog) -> Event:
    new_value = _scrub_value(event.id, event.value, log)
    redacted = new_value != event.value
    return event.model_copy(update={"value": new_value, "redacted": event.redacted or redacted})


def _scrub_value(event_id: str, value: Any, log: RedactionLog) -> Any:
    if isinstance(value, str):
        return _scrub_string(event_id, value, log)
    if isinstance(value, dict):
        return {k: _scrub_value(event_id, v, log) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_value(event_id, v, log) for v in value]
    return value


def _scrub_string(event_id: str, text: str, log: RedactionLog) -> str:
    out = text
    for kind, pattern in _PATTERNS:
        def _sub(match: re.Match[str]) -> str:
            placeholder = log.next_placeholder(kind)
            log.redactions.append(
                Redaction(
                    event_id=event_id,
                    placeholder=placeholder,
                    kind=kind,
                    original_length=len(match.group(0)),
                )
            )
            return placeholder

        out = pattern.sub(_sub, out)

    if (
        len(out) >= _HIGH_ENTROPY_MIN_LEN
        and "<" not in out
        and _shannon_entropy(out) >= _HIGH_ENTROPY_THRESHOLD
        and _looks_like_secret(out)
    ):
        placeholder = log.next_placeholder("HIGH_ENTROPY")
        log.redactions.append(
            Redaction(
                event_id=event_id,
                placeholder=placeholder,
                kind="HIGH_ENTROPY",
                original_length=len(out),
            )
        )
        return placeholder

    return out


def _shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts: dict[str, int] = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    total = len(text)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def _looks_like_secret(text: str) -> bool:
    """Filter that prevents ordinary prose from tripping the entropy heuristic."""
    if " " in text.strip():
        return False
    has_alpha = any(c.isalpha() for c in text)
    has_digit = any(c.isdigit() for c in text)
    return has_alpha and has_digit
