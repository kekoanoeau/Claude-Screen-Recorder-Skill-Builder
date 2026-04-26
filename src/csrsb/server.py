"""Local HTTP receiver for browser-extension uploads.

Run with ``csrsb serve [--port 7778] [--out DIR]``. The browser extension POSTs
a JSON payload to ``POST /recordings``; we split the inline base64 screenshots
out into ``screenshots/<ts>.png`` files and write the canonical
``recording.json`` to a fresh subdirectory under ``--out``.

We use the stdlib ``http.server`` (no extra dependencies) — Phase 4 may swap to
FastAPI if we need WebSockets or richer validation, but for one-localhost-client
single-upload-at-a-time, the stdlib is enough.
"""

from __future__ import annotations

import base64
import json
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from csrsb.ingest.browser import from_payload

# Origins we trust to POST recordings to us. ``chrome-extension://*`` covers
# every loaded extension; ``moz-extension://*`` covers Firefox if we ever ship
# there. Pages on the public internet must not be able to drive this endpoint.
_ALLOWED_ORIGIN_PREFIXES = ("chrome-extension://", "moz-extension://")
_DEFAULT_PORT = 7778
_MAX_BODY_BYTES = 256 * 1024 * 1024  # 256 MB — generous; protects against runaway uploads


class _RecordingHandler(BaseHTTPRequestHandler):
    server_version = "csrsb/0.1"

    # Injected by ``serve()``. ``Path`` because we mkdir per-recording.
    out_root: Path  # type: ignore[assignment]

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 — stdlib name
        # Keep the default stderr access log; users running ``csrsb serve`` want it.
        super().log_message(format, *args)

    def do_OPTIONS(self) -> None:  # noqa: N802 — stdlib name
        self._send_cors_preflight()

    def do_POST(self) -> None:  # noqa: N802 — stdlib name
        if self.path != "/recordings":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        if not self._origin_allowed():
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "origin not allowed"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "empty body"})
            return
        if length > _MAX_BODY_BYTES:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "body too large"})
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": f"invalid JSON: {exc}"})
            return

        try:
            recording_dir = save_payload(payload, out_root=self.out_root)
        except ValueError as exc:
            self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 — unknown writer failure; log and 500
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"write failed: {exc}"})
            return

        self._send_json(
            HTTPStatus.CREATED,
            {"path": str(recording_dir.resolve()), "name": recording_dir.name},
        )

    def _send_cors_preflight(self) -> None:
        if not self._origin_allowed():
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "origin not allowed"})
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._set_cors_headers()
        self.end_headers()

    def _send_json(self, status: HTTPStatus, body: dict[str, object]) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _set_cors_headers(self) -> None:
        origin = self.headers.get("Origin", "")
        if self._origin_allowed():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin", "")
        return any(origin.startswith(p) for p in _ALLOWED_ORIGIN_PREFIXES)


def save_payload(payload: dict[str, object], *, out_root: Path) -> Path:
    """Split inline base64 screenshots out into PNG files and write recording.json.

    Returns the directory the recording was written to.
    """
    out_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    rec_dir = out_root / f"browser-{timestamp}"
    suffix = 1
    while rec_dir.exists():
        rec_dir = out_root / f"browser-{timestamp}-{suffix}"
        suffix += 1
    screenshots_dir = rec_dir / "screenshots"
    screenshots_dir.mkdir(parents=True)

    events = payload.get("events")
    if not isinstance(events, list):
        raise ValueError("payload missing 'events' array")
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("event entries must be objects")
        data_b64 = event.pop("screenshot_data", None)
        if isinstance(data_b64, str) and data_b64:
            try:
                blob = base64.standard_b64decode(data_b64)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"invalid base64 screenshot on {event.get('id')}") from exc
            filename = f"{event.get('id', 'evt')}.png"
            (screenshots_dir / filename).write_bytes(blob)
            event["screenshot_path"] = f"screenshots/{filename}"

    recording = from_payload(payload)
    recording.write_to_dir(rec_dir)
    return rec_dir


def serve(out_dir: Path, *, port: int = _DEFAULT_PORT, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Construct (but do not start) the HTTP server. Caller runs ``serve_forever``.

    Bound to localhost by default — never bind to 0.0.0.0; the upload contains
    full-window screenshots and we don't want them exposed on a LAN.
    """
    handler = type("_Handler", (_RecordingHandler,), {"out_root": Path(out_dir)})
    return ThreadingHTTPServer((host, port), handler)


def run(out_dir: Path, *, port: int = _DEFAULT_PORT) -> None:
    """Block, serving until interrupted. Used by the CLI."""
    server = serve(out_dir, port=port)
    print(f"csrsb serve listening on http://127.0.0.1:{port} (writing to {out_dir})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


def run_in_thread(out_dir: Path, *, port: int = 0) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Spawn the server on a background thread (used by tests).

    Pass ``port=0`` to bind an ephemeral port; read it back via
    ``server.server_address``.
    """
    server = serve(out_dir, port=port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
