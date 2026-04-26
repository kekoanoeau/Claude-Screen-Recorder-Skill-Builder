# Claude Screen Recorder Skill Builder

Record yourself doing a task on your desktop or in a browser, and turn the recording into a [Claude Code Skill](https://platform.claude.com/docs/en/agents-and-tools/skills) so Claude can do it for you next time.

## Status — Phase 2 (desktop + browser end-to-end)

Phases 1 and 2 are implemented. The desktop loop ships as before, plus a Manifest V3 browser extension, a localhost upload receiver, and a two-pass translator (Haiku 4.5 labels each segment, Opus 4.7 synthesises the skill):

```
# Desktop
csrsb record           →  recording.json + screenshots
csrsb build            →  SKILL.md + reference/
csrsb install          →  ~/.claude/skills/<name>/

# Browser
csrsb serve --out DIR  →  receives uploads from the Chrome/Edge extension
csrsb build DIR        →  same translator pipeline as desktop
csrsb install …        →  same install path as desktop
```

OCR-based screenshot redaction, the post-LLM secret check, the deterministic-replay script generator, and `csrsb describe` land in Phases 3–4 (see [the plan](#roadmap)).

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
| `csrsb record --out DIR [--stop-chord ctrl+shift+esc] [--intent "..."] [--no-screenshots]` | Records a desktop session. Captures clicks, scrolls, keystrokes (collapsed into typed strings), and a screenshot per click. Stops when the stop chord fires. |
| `csrsb serve --out DIR [--port 7778]` | Listens on localhost for uploads from the browser extension. Splits inline base64 screenshots into PNG files and writes a recording.json under `<out>/browser-<timestamp>/`. |
| `csrsb build RECORDING_DIR --out DIR [--allow-pii] [--overwrite]` | Runs compress → multi-signal segment → redact → Haiku label → Opus synthesize. Auto-detects desktop vs. browser surface from the recording. Writes `<out>/<name>/`. |
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
- **Phase 2 (this release)** — Manifest V3 browser extension + `csrsb serve` HTTP receiver, frame/shadow walk + selector ranking, Haiku per-step labeling pass, multi-signal weighted segmenter ✅
- **Phase 3** — drag/drop, clipboard, hover-with-dwell, focus changes, perceptual-hash boundaries, OCR-based screenshot redaction, post-LLM secret check, optional `--with-script` deterministic replay generator
- **Phase 4** — `csrsb describe` interactive description refiner, prompt-cache hit metrics, conflict detection on install, optional face-blur

## License

MIT.
