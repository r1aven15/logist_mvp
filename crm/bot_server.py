#!/usr/bin/env python3
"""Tiny HTTP API for the FAQ bot. A MAX/Telegram adapter can call POST /ask."""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from faq_bot import answer, load


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send({"ok": True})
            return
        if parsed.path != "/ask":
            self._send({"error": "not found"}, 404)
            return
        text = parse_qs(parsed.query).get("q", [""])[0]
        self._send({"answer": answer(text, load())})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/ask":
            self._send({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send({"error": "invalid json"}, 400)
            return
        text = str(payload.get("text", ""))
        self._send({"answer": answer(text, load())})

    def log_message(self, fmt: str, *args) -> None:
        print("%s - %s" % (self.address_string(), fmt % args))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"FAQ API: http://{args.host}:{args.port}/ask?q=...")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
