from __future__ import annotations

from datetime import datetime, timezone

from csrsb.schema import Event, Recording, SelectorAlternatives, Target
from csrsb.translator.scripts import generate_replay_script


def _rec(surface: str, *events: Event) -> Recording:
    return Recording(
        surface=surface,
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
        events=list(events),
    )


def test_browser_script_uses_testid_selector_and_goto() -> None:
    rec = _rec(
        "browser",
        Event(
            id="evt_0001",
            ts_ms=0,
            surface="browser",
            type="navigate",
            target=Target(url="https://example.test/login"),
        ),
        Event(
            id="evt_0002",
            ts_ms=200,
            surface="browser",
            type="click",
            target=Target(
                url="https://example.test/login",
                selector_alternatives=SelectorAlternatives(
                    testid='[data-testid="login-button"]',
                    css="button.login",
                ),
            ),
        ),
    )
    script = generate_replay_script(rec)
    assert "from playwright.sync_api import sync_playwright" in script
    assert 'page.goto("https://example.test/login")' in script
    assert 'page.locator("[data-testid=\\"login-button\\"]").click()' in script


def test_browser_script_falls_back_to_css_when_testid_missing() -> None:
    rec = _rec(
        "browser",
        Event(
            id="evt_0001",
            ts_ms=0,
            surface="browser",
            type="click",
            target=Target(
                url="https://example.test",
                selector_alternatives=SelectorAlternatives(css="button.submit"),
            ),
        ),
    )
    script = generate_replay_script(rec)
    assert 'page.locator("button.submit").click()' in script


def test_desktop_script_emits_pyautogui_calls_with_throttled_waits() -> None:
    rec = _rec(
        "desktop",
        Event(id="evt_0001", ts_ms=0, surface="desktop", type="click",
              value={"x": 100, "y": 200, "button": "left"}),
        Event(id="evt_0002", ts_ms=10_000_000, surface="desktop", type="input", value="hi"),
    )
    script = generate_replay_script(rec)
    assert "import pyautogui" in script
    assert 'pyautogui.click(100, 200, button="left")' in script
    assert 'pyautogui.typewrite("hi"' in script
    # 10_000_000ms gap should be capped at 3.0s.
    assert "time.sleep(3.00)" in script


def test_desktop_script_skips_unknown_events() -> None:
    rec = _rec(
        "desktop",
        Event(
            id="evt_0001",
            ts_ms=0,
            surface="desktop",
            type="screen_changed",
            value={"hamming": 20},
        ),
    )
    script = generate_replay_script(rec)
    # No bogus pyautogui call for an event we can't replay.
    assert "pyautogui.click" not in script
    assert "pyautogui.typewrite" not in script
