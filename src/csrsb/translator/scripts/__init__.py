"""Deterministic-replay script generators (Phase 3, opt-in via ``--with-script``).

These produce best-effort scripts that mechanically replay the recording —
Playwright for browser, pyautogui for desktop. They sit *under* the semantic
SKILL.md as a fallback: Claude follows the natural-language steps first, but
can shell out to ``scripts/replay.py`` when it needs deterministic playback
(or when a step's selector definitely won't have drifted).
"""

from csrsb.translator.scripts.generator import generate_replay_script

__all__ = ["generate_replay_script"]
