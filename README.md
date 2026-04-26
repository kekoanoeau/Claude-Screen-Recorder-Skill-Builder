# Claude Screen Recorder Skill Builder

Record yourself doing a task on your desktop or in a browser, and turn the recording into a [Claude Code Skill](https://platform.claude.com/docs/en/agents-and-tools/skills) so Claude can do it for you next time.

## Status — Phase 3 (quality & robustness)

Phases 1–3 are implemented. Phase 3 hardens the recorders, adds defense-in-depth on the privacy side, and lets the skill optionally ship with a deterministic-replay scaffold:

| Area | What's new in Phase 3 |
|---|---|
| **Browser** | drag/drop, hover-with-dwell, copy/paste (length+sha256, never the contents), tab open/close/switch, window focus_change |
| **Desktop** | OS-level `focus_change` polling (macOS via `osascript`, Linux via `xdotool`), perceptual-hash → `screen_changed` boundary events |
| **Privacy** | Post-LLM secret check (Haiku reviews the rendered SKILL.md and fails the build unless `--allow-pii`); OCR-based screenshot redaction (opt-in via `--ocr-redact`, gracefully no-ops if pytesseract is missing) |
| **Replay** | `csrsb build --with-script` emits `scripts/replay.py` — Playwright for browser recordings, pyautogui for desktop |

`csrsb describe` (interactive description refiner) and prompt-cache hit metrics land in Phase 4.

## What gets generated

The translator emits a Claude Code Skill — a directory shaped like:

```
<skill-name>/
├── SKILL.md                # YAML frontmatter (name, description) + body
└── reference/
    ├── original_recording.json
    ├── REDACTIONS.md       # every secret/PII redaction applied during build
    └── screenshots/        # frames from the recording
```

The body is **semantic**, not literal — it tells Claude *what* to do in natural language so it can adapt to UI changes, rather than replaying recorded coordinates. Each step has a **Goal**, **Action**, **Expected result**, and an optional **If it fails** fallback so Claude can self-correct mid-execution.

## Install

Requires Python 3.10+.

```sh
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...
```

The desktop recorder depends on `pynput` (keyboard/mouse) and `mss` (screenshots). On Linux you may need an X11 display server; on macOS, grant Accessibility + Screen Recording permission to your terminal.

## Use

```sh
# 1. Record a task — performs whatever workflow you want Claude to learn
csrsb record --out /tmp/calc-rec --intent "open Calculator and compute 2+2"
# (the recorder runs until you press Ctrl+Shift+Esc, the default stop chord)

# 2. Translate the recording into a skill
csrsb build /tmp/calc-rec --out /tmp/skills

# 3. Verify the generated SKILL.md is well-formed
csrsb validate /tmp/skills/open-calculator-and-add

# 4. Install into the user-scope Claude skills directory
csrsb install /tmp/skills/open-calculator-and-add --scope user
#   (use --scope project to install into ./.claude/skills/ instead)

# Now in Claude Code: ask Claude to use the skill — it will load
# SKILL.md and follow the recorded steps semantically.
```

### CLI reference

| Command | What it does |
|---|---|
| `csrsb record --out DIR [--stop-chord ctrl+shift+esc] [--intent "..."] [--no-screenshots] [--ocr-redact] [--no-focus-poll]` | Records a desktop session. Captures clicks, scrolls, keystrokes (collapsed into typed strings), screenshots, OS focus changes, and `screen_changed` boundaries. `--ocr-redact` blurs secret-shaped regions from each screenshot before saving (requires pytesseract). |
| `csrsb serve --out DIR [--port 7778]` | Listens on localhost for uploads from the browser extension. Splits inline base64 screenshots into PNG files and writes a recording.json under `<out>/browser-<timestamp>/`. |
| `csrsb build RECORDING_DIR --out DIR [--with-script] [--allow-pii] [--skip-secret-check] [--overwrite]` | Runs compress → multi-signal segment → redact → Haiku label → Opus synthesize → Haiku secret-check. Auto-detects desktop vs. browser. `--with-script` emits an additional `scripts/replay.py` (Playwright for browser, pyautogui for desktop). |
| `csrsb install SKILL_DIR [--scope user|project] [--overwrite]` | Copies the skill to `~/.claude/skills/` (default) or `./.claude/skills/`. |
| `csrsb validate SKILL_DIR` | Lints frontmatter (`name` kebab-case, `description` ≤ 1024 chars) and image references. |

### Browser extension

Living under `recorders/browser-extension/`. Load it as an unpacked extension (`chrome://extensions/` → Developer mode → Load unpacked). The popup provides Start / Stop / Add note. Events are captured via capturing-phase listeners; password fields and `autocomplete=one-time-code|cc-*` fields are skipped at the source. Screenshots are taken via `chrome.tabs.captureVisibleTab` from the background service worker; an offscreen document keepalive prevents the worker from being torn down between events. Recordings either upload to `csrsb serve` or download as a JSON file with inline base64 screenshots.

### Privacy posture

Phase 1 redaction is regex-based and runs in the translator — passwords, API keys (`sk-`, `ghp_`, `AKIA…`, JWT, Bearer headers), emails, phones, SSNs, and high-entropy strings are replaced with typed placeholders (`<EMAIL_1>`, `<TOKEN_1>`) before any data leaves your machine for Anthropic. Every replacement is logged to `reference/REDACTIONS.md` next to the generated skill so you can review before installing.

Phase 3 will add OCR-based screenshot redaction and a post-LLM secret-leak check; for now, **avoid recording windows that show secrets directly on screen** (the screenshots are sent to Claude as-is for context).

## Architecture

```
src/csrsb/
├── recorders/desktop/    # pynput + mss capture, lifecycle, hotkey
├── ingest/               # raw recorder dump -> Recording (uniform across surfaces)
│   ├── desktop.py        # thin loader (the desktop recorder writes the canonical shape)
│   └── browser.py        # validate + renumber + Recording.from_dict for extension uploads
├── server.py             # csrsb serve — localhost HTTP receiver for browser uploads
├── translator/           # compress -> segment -> redact -> Haiku label -> Opus synth
│   ├── prompts/          # system prompts + JSON schemas for StepLabel and SkillDraft
│   └── templates/        # Jinja2 SKILL.md.j2 + REDACTIONS.md.j2
├── builder.py            # render templates, write skill dir
├── installer.py          # copy to ~/.claude/skills/ or ./.claude/skills/
├── cli.py                # record | serve | build | install | validate
└── schema.py             # Pydantic Recording, Event, Target, Step, SkillDraft

recorders/browser-extension/   # Manifest V3 — separate dir because it ships unpacked
├── manifest.json
├── background.js         # service worker: event buffer, captureVisibleTab, upload
├── content.js            # capturing-phase listeners + selector ranking + frame/shadow walk
├── offscreen.html / offscreen.js   # keepalive for the service worker
└── popup.html / popup.js
```

Both recorders emit the same `Recording` shape, so the translator never branches on the recording surface.

## Develop

```sh
pip install -e ".[dev]"
pytest
```

The test suite ships with a desktop fixture recording (`tests/fixtures/recordings/calculator/`) and a fake `ClaudeClient` so the full pipeline runs offline without an API key.

## Roadmap

- **Phase 1** — desktop recorder, single-pass Opus synthesis, regex redaction, end-to-end CLI ✅
- **Phase 2** — Manifest V3 browser extension + `csrsb serve` HTTP receiver, frame/shadow walk + selector ranking, Haiku per-step labeling pass, multi-signal weighted segmenter ✅
- **Phase 3 (this release)** — drag/drop, clipboard, hover-with-dwell, focus changes (browser + OS-level), perceptual-hash boundaries, OCR-based screenshot redaction, post-LLM secret check, `--with-script` deterministic replay generator ✅
- **Phase 4** — `csrsb describe` interactive description refiner, prompt-cache hit metrics, conflict detection on install, optional face-blur

## License

MIT.
