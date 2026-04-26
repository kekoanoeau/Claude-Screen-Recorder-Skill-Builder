from __future__ import annotations

from datetime import datetime, timezone

from csrsb.schema import Event, Recording
from csrsb.translator.redact import scrub


def _rec(*events: Event) -> Recording:
    return Recording(
        surface="desktop",
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
        events=list(events),
    )


def _evt(value: object, idx: int = 1) -> Event:
    return Event(
        id=f"evt_{idx:04d}",
        ts_ms=idx * 100,
        surface="desktop",
        type="input",
        value=value,
    )


def test_email_is_replaced_with_placeholder() -> None:
    rec = _rec(_evt("contact alice@example.com please"))
    scrubbed, log = scrub(rec)
    assert scrubbed.events[0].value == "contact <EMAIL_1> please"
    assert scrubbed.events[0].redacted is True
    assert log.redactions[0].kind == "EMAIL"


def test_anthropic_key_in_dict_value_is_replaced() -> None:
    rec = _rec(_evt({"key": "x", "extra": "sk-ant-" + "a" * 64}))
    scrubbed, log = scrub(rec)
    assert scrubbed.events[0].value["extra"].startswith("<ANTHROPIC_KEY_")
    assert log.redactions[0].kind == "ANTHROPIC_KEY"


def test_benign_text_is_left_alone() -> None:
    rec = _rec(_evt("hello world"))
    scrubbed, log = scrub(rec)
    assert scrubbed.events[0].value == "hello world"
    assert log.redactions == []
