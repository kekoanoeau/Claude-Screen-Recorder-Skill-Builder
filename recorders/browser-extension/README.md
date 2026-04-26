# csrsb browser extension

Manifest V3 extension that captures clicks, typed text, navigation, scrolls,
and file uploads, then either uploads the recording to a local
`csrsb serve` instance or downloads it as JSON.

## Loading it (Chrome / Edge)

1. Run `csrsb serve --out ./recordings/` to start the local receiver.
2. In Chrome, open `chrome://extensions/`.
3. Enable **Developer mode** (top right).
4. Click **Load unpacked** and pick this directory.
5. Pin the extension and click its icon to open the popup.

## Recording

1. Open the popup.
2. (Optional) Type a free-text intent — what task are you recording?
3. Confirm the local upload URL (default `http://127.0.0.1:7778/recordings`).
   Leave it blank to download the recording as a JSON file instead.
4. Click **Start**.
5. Perform the workflow.
6. Click **Stop**. The recording is uploaded (or downloaded) and appears in
   `recordings/<browser-YYYYMMDDTHHMMSS>/`.
7. Run `csrsb build recordings/browser-… --out skills/` to translate it.

## Privacy posture

The content script never sends the contents of password fields or fields whose
`autocomplete` indicates a password / one-time code / credit card to the
background. Screenshots are still captured for the surrounding context — keep
sensitive windows out of view.

The translator runs an additional regex sweep over event values for known
secret formats (API keys, JWTs, emails, etc.) before any data leaves your
machine for Anthropic.

## Icons

The `icons/` directory is intentionally not checked in. Drop 16×16, 48×48,
and 128×128 PNG icons there to satisfy the manifest, or remove the `icons`
block from `manifest.json` while developing.
