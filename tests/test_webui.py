from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from cardpack.webui import Handler
from tests.conftest import b64_json, build_png, card_v2_payload


@pytest.fixture
def live_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base_url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _post(url: str, data: bytes, headers: dict | None = None):
    req = urllib.request.Request(url, data=data, method="POST", headers=headers or {})
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read())


def test_serves_index_html(live_server):
    with urllib.request.urlopen(f"{live_server}/") as resp:
        assert resp.status == 200
        body = resp.read().decode("utf-8")
        assert "<title>BestCards</title>" in body


def test_serves_app_js_and_styles_css(live_server):
    with urllib.request.urlopen(f"{live_server}/app.js") as resp:
        assert resp.status == 200
        assert b"processFiles" in resp.read()
    with urllib.request.urlopen(f"{live_server}/styles.css") as resp:
        assert resp.status == 200


def test_unknown_path_is_404(live_server):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{live_server}/does-not-exist")
    assert exc_info.value.code == 404


def test_path_traversal_is_blocked(live_server):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{live_server}/../pyproject.toml")
    assert exc_info.value.code == 404


def test_api_extract_returns_card_for_valid_png(live_server):
    png_bytes = build_png([("tEXt", "chara", b64_json(card_v2_payload(name="Aria")))])
    status, data = _post(f"{live_server}/api/extract?name=aria.png", png_bytes)
    assert status == 200
    assert data["ok"] is True
    assert data["card"]["name"] == "Aria"
    assert data["card"]["source_file"] == "aria.png"


def test_api_extract_reports_failure_for_non_card_png(live_server):
    png_bytes = build_png([("tEXt", "Software", "unrelated")])
    status, data = _post(f"{live_server}/api/extract?name=bad.png", png_bytes)
    assert status == 200
    assert data["ok"] is False
    assert "bad.png" in data["filename"]


def test_api_export_roundtrip_markdown(live_server):
    png_bytes = build_png([("tEXt", "chara", b64_json(card_v2_payload(name="Aria")))])
    _, extract_data = _post(f"{live_server}/api/extract?name=aria.png", png_bytes)
    card = extract_data["card"]

    body = json.dumps({"cards": [card], "format": "md", "full": False, "max_chars": 600}).encode("utf-8")
    status, data = _post(f"{live_server}/api/export", body, {"Content-Type": "application/json"})
    assert status == 200
    assert data["filename"] == "cards_export.md"
    assert "Aria" in data["content"]


def test_api_export_compact_and_json_formats(live_server):
    png_bytes = build_png([("tEXt", "chara", b64_json(card_v2_payload(name="Aria")))])
    _, extract_data = _post(f"{live_server}/api/extract?name=aria.png", png_bytes)
    card = extract_data["card"]

    for fmt, ext in (("compact", "txt"), ("json", "json")):
        body = json.dumps({"cards": [card], "format": fmt}).encode("utf-8")
        status, data = _post(f"{live_server}/api/export", body, {"Content-Type": "application/json"})
        assert status == 200
        assert data["filename"] == f"cards_export.{ext}"
        assert "Aria" in data["content"]


def test_api_estimate_returns_total_and_per_card_tokens(live_server):
    png_bytes = build_png([("tEXt", "chara", b64_json(card_v2_payload(name="Aria")))])
    _, extract_data = _post(f"{live_server}/api/extract?name=aria.png", png_bytes)
    card = extract_data["card"]

    body = json.dumps({"cards": [card], "format": "compact", "full": False, "max_chars": 600}).encode("utf-8")
    status, data = _post(f"{live_server}/api/estimate", body, {"Content-Type": "application/json"})
    assert status == 200
    assert data["total_tokens"] > 0
    assert "method" in data
    assert len(data["cards"]) == 1
    assert data["cards"][0]["name"] == "Aria"


def test_api_export_respects_fields_selection(live_server):
    png_bytes = build_png(
        [("tEXt", "chara", b64_json(card_v2_payload(name="Aria", creator_notes="Loved for its banter.")))]
    )
    _, extract_data = _post(f"{live_server}/api/extract?name=aria.png", png_bytes)
    card = extract_data["card"]

    body = json.dumps({"cards": [card], "format": "compact", "fields": ["tags"]}).encode("utf-8")
    _, without_notes = _post(f"{live_server}/api/export", body, {"Content-Type": "application/json"})
    assert "banter" not in without_notes["content"]

    body = json.dumps({"cards": [card], "format": "compact", "fields": ["tags", "creator_notes"]}).encode("utf-8")
    _, with_notes = _post(f"{live_server}/api/export", body, {"Content-Type": "application/json"})
    assert "banter" in with_notes["content"]
