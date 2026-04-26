# Claude Screen Recorder Skill Builder

Record yourself doing a task on your desktop or in a browser, and turn the recording into a [Claude Code Skill](https://platform.claude.com/docs/en/agents-and-tools/skills) so Claude can do it for you next time.

## Status — Phase 1 (desktop MVP)

Phase 1 is implemented. It supports the full desktop loop:

```
csrsb record  →  recording.json + screenshots
csrsb build   →  SKILL.md + reference/  (Claude Opus 4.7 synthesis)
csrsb install →  ~/.claude/skills/<name>/  (or .claude/skills/<name>/)
```

The browser extension, the multi-signal segmenter, drag/upload/clipboard/focus events, OCR-based screenshot redaction, and the deterministic-replay script generator land in Phases 2–4 (see [the plan](#roadmap)).

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
| `csrsb build RECORDING_DIR --out DIR [--allow-pii] [--overwrite]` | Runs compress → segment → redact → synthesize via Claude Opus 4.7. Writes `<out>/<name>/`. Warns about any redactions found unless `--allow-pii`. |
| `csrsb install SKILL_DIR [--scope user|project] [--overwrite]` | Copies the skill to `~/.claude/skills/` (default) or `./.claude/skills/`. |
| `csrsb validate SKILL_DIR` | Lints frontmatter (`name` kebab-case, `description` ≤ 1024 chars) and image references. |

### Privacy posture

Phase 1 redaction is regex-based and runs in the translator — passwords, API keys (`sk-`, `ghp_`, `AKIA…`, JWT, Bearer headers), emails, phones, SSNs, and high-entropy strings are replaced with typed placeholders (`<EMAIL_1>`, `<TOKEN_1>`) before any data leaves your machine for Anthropic. Every replacement is logged to `reference/REDACTIONS.md` next to the generated skill so you can review before installing.

Phase 3 will add OCR-based screenshot redaction and a post-LLM secret-leak check; for now, **avoid recording windows that show secrets directly on screen** (the screenshots are sent to Claude as-is for context).

## Architecture

```
csrsb/
├── recorders/desktop/    # pynput + mss capture, lifecycle, hotkey
├── ingest/               # raw recorder dump -> Recording (uniform across surfaces)
├── translator/           # compress -> segment -> redact -> Claude synthesis
│   ├── prompts/          # system prompt + JSON schema for SkillDraft
│   └── templates/        # Jinja2 SKILL.md.j2 + REDACTIONS.md.j2
├── builder.py            # render templates, write skill dir
├── installer.py          # copy to ~/.claude/skills/ or ./.claude/skills/
├── cli.py                # record | build | install | validate
└── schema.py             # Pydantic Recording, Event, Target, Step, SkillDraft
```

Both recorders (desktop now, browser in Phase 2) emit the same `Recording` shape, so the translator never branches on the recording surface.

## Develop

```sh
pip install -e ".[dev]"
pytest
```

The test suite ships with a desktop fixture recording (`tests/fixtures/recordings/calculator/`) and a fake `ClaudeClient` so the full pipeline runs offline without an API key.

## Roadmap

- **Phase 1 (this release)** — desktop recorder, single-pass Opus synthesis, regex redaction, end-to-end CLI
- **Phase 2** — Manifest V3 browser extension + `csrsb serve` HTTP receiver, multi-tab/iframe/shadow-DOM, Haiku per-step labeling, multi-signal segmenter
- **Phase 3** — drag/drop, file_upload, clipboard, hover-with-dwell, focus changes, perceptual-hash boundaries, OCR-based screenshot redaction, post-LLM secret check, optional `--with-script` deterministic replay generator
- **Phase 4** — `csrsb describe` interactive description refiner, prompt-cache hit metrics, conflict detection on install, optional face-blur

## License

MIT.
