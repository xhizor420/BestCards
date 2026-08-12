"""Local web UI: drag-and-drop / click-to-browse PNG batch extraction.

Runs a small stdlib-only HTTP server (no Flask, nothing to install) that
serves a single-page app and two JSON endpoints:

  POST /api/extract?name=<filename>   body = raw PNG bytes
      -> {"ok": true, "card": {...}} | {"ok": false, "error": "..."}

  POST /api/export                    body = JSON
      {"cards": [...], "format": "md"|"compact"|"json", "full": bool,
       "max_chars": int, "sort": "name"|"file", "fields": ["tags", ...]}
      -> {"filename": "...", "content": "..."}

  POST /api/estimate                  body = JSON (same shape as /api/export
      minus "sort") -> {"total_tokens": int, "method": "...",
                         "cards": [{"index", "name", "tokens"}, ...]}

The browser does the fan-out: it uploads PNGs to /api/extract with a small
concurrency pool, updates a progress counter as each response lands, then
collects the successful cards and posts them all to /api/export to get the
combined file back for download. All processing stays on localhost.
"""

from __future__ import annotations

import json
import socket
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .cardspec import Card, CardExtractionError, parse_card_payload
from .formats import WRITERS, card_to_dict, estimate_export
from .png_chunks import NotAPngError, read_text_chunks

STATIC_DIR = (Path(__file__).parent / "webui_static").resolve()

_EXTENSIONS = {"md": "md", "compact": "txt", "json": "json"}

_STATIC_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "BestCardsUI/0.1"

    def log_message(self, fmt: str, *args) -> None:  # quieter default logging
        pass

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming convention)
        path = urlparse(self.path).path
        if path == "/":
            path = "/index.html"
        candidate = (STATIC_DIR / path.lstrip("/")).resolve()
        if STATIC_DIR not in candidate.parents and candidate != STATIC_DIR:
            self.send_error(404)
            return
        if not candidate.is_file():
            self.send_error(404)
            return
        content_type = _STATIC_CONTENT_TYPES.get(candidate.suffix, "application/octet-stream")
        data = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""

        if parsed.path == "/api/extract":
            self._handle_extract(parsed, body)
        elif parsed.path == "/api/export":
            self._handle_export(body)
        elif parsed.path == "/api/estimate":
            self._handle_estimate(body)
        else:
            self.send_error(404)

    def _handle_extract(self, parsed, body: bytes) -> None:
        query = parse_qs(parsed.query)
        filename = (query.get("name") or ["upload.png"])[0]
        try:
            chunks = read_text_chunks(body)
            card = parse_card_payload(chunks)
            card.source_file = filename
            self._send_json(200, {"ok": True, "card": card_to_dict(card, full=True)})
        except NotAPngError as e:
            self._send_json(200, {"ok": False, "filename": filename, "error": str(e)})
        except CardExtractionError as e:
            self._send_json(200, {"ok": False, "filename": filename, "error": str(e)})
        except Exception as e:  # noqa: BLE001 - one bad file shouldn't kill the batch
            self._send_json(200, {"ok": False, "filename": filename, "error": f"unexpected error: {e}"})

    def _handle_export(self, body: bytes) -> None:
        try:
            payload = json.loads(body.decode("utf-8"))
            fmt = payload.get("format", "md")
            if fmt not in WRITERS:
                self._send_json(400, {"error": f"unknown format {fmt!r}"})
                return
            full = bool(payload.get("full", False))
            max_chars = payload.get("max_chars", 600)
            sort_key = payload.get("sort", "name")
            fields = payload.get("fields", ["tags"])

            cards = [Card.from_dict(d) for d in payload.get("cards", [])]
            if sort_key == "name":
                cards.sort(key=lambda c: (c.name or c.nickname or "").lower())
            else:
                cards.sort(key=lambda c: c.source_file)

            content = WRITERS[fmt](cards, full=full, max_chars=max_chars, extra_fields=fields)
            filename = f"cards_export.{_EXTENSIONS[fmt]}"
            self._send_json(200, {"filename": filename, "content": content})
        except Exception as e:  # noqa: BLE001
            self._send_json(400, {"error": str(e)})

    def _handle_estimate(self, body: bytes) -> None:
        try:
            payload = json.loads(body.decode("utf-8"))
            fmt = payload.get("format", "md")
            if fmt not in WRITERS:
                self._send_json(400, {"error": f"unknown format {fmt!r}"})
                return
            full = bool(payload.get("full", False))
            max_chars = payload.get("max_chars", 600)
            fields = payload.get("fields", ["tags"])
            cards = [Card.from_dict(d) for d in payload.get("cards", [])]
            self._send_json(200, estimate_export(cards, format=fmt, full=full, max_chars=max_chars, extra_fields=fields))
        except Exception as e:  # noqa: BLE001
            self._send_json(400, {"error": str(e)})


def _find_free_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("could not find a free port")


def run_server(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    actual_port = _find_free_port(port)
    server = ThreadingHTTPServer((host, actual_port), Handler)
    url = f"http://{host}:{actual_port}/"
    print(f"BestCards UI running at {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="bestcards-ui", description="Launch the BestCards browser UI.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open a browser tab.")
    args = parser.parse_args(argv)
    run_server(host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
