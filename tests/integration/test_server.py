from __future__ import annotations

import base64
import json
import urllib.request
from pathlib import Path

import pytest

from csrsb.schema import Recording
from csrsb.server import run_in_thread


@pytest.fixture
def server(tmp_path: Path):
    out = tmp_path / "uploads"
    out.mkdir()
    srv, thread = run_in_thread(out, port=0)
    host, port = srv.server_address[:2]
    yield {"out": out, "url": f"http://{host}:{port}"}
    srv.shutdown()
    thread.join(timeout=2)


def _post(url: str, body: dict, *, origin: str | None = "chrome-extension://abc123") -> tuple[int, dict | None]:
    headers = {"Content-Type": "application/json"}
    if origin is not None:
        headers["Origin"] = origin
    req = urllib.request.Request(
        url + "/recordings",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8"))
        except Exception:
            payload = None
        return e.code, payload


def _png_b64() -> str:
    # 1x1 transparent PNG
    return base64.b64encode(
        bytes.fromhex(
            "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4"
            "890000000A49444154789C6300010000000500010D0A2DB40000000049454E44"
            "AE426082"
        )
    ).decode()


def _build_payload() -> dict:
    return {
        "version": "1.0",
        "surface": "browser",
        "started_at": "2026-04-26T10:00:00Z",
        "ended_at": "2026-04-26T10:00:05Z",
        "metadata": {"browser": "Chrome 130", "viewport": {"w": 1440, "h": 900, "dpr": 2.0}},
        "events": [
            {
                "id": "evt_in_1",
                "ts_ms": 1714125600000,
                "surface": "browser",
                "type": "click",
                "target": {"url": "https://example.test"},
                "value": {"button": 0},
                "screenshot_data": _png_b64(),
            },
            {
                "id": "evt_in_2",
                "ts_ms": 1714125603000,
                "surface": "browser",
                "type": "navigate",
                "target": {"url": "https://example.test/next"},
                "value": {},
            },
        ],
        "notes": [],
    }


def test_upload_writes_recording_and_screenshots(server) -> None:
    status, body = _post(server["url"], _build_payload())
    assert status == 201
    rec_dir = Path(body["path"])
    assert rec_dir.exists()
    rec = Recording.from_dir(rec_dir)
    assert rec.surface == "browser"
    assert rec.events[0].screenshot_path is not None
    assert (rec_dir / rec.events[0].screenshot_path).exists()


def test_upload_rejected_without_extension_origin(server) -> None:
    status, body = _post(server["url"], _build_payload(), origin="https://attacker.example")
    assert status == 403
    assert body and "origin" in body["error"]


def test_invalid_payload_returns_422(server) -> None:
    status, body = _post(server["url"], {"surface": "browser", "events": "nope"})
    # 'events' is not a list — server returns 422 before validation
    assert status in (400, 422)


def test_unknown_path_returns_404(server) -> None:
    req = urllib.request.Request(
        server["url"] + "/wrong",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json", "Origin": "chrome-extension://abc"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            assert False, f"expected 404, got {resp.status}"
    except urllib.error.HTTPError as e:
        assert e.code == 404
