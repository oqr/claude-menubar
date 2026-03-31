#!/usr/bin/env python3
"""Tiny HTTP server that receives Claude usage data from browser userscript.

Listens on 127.0.0.1:19222 and writes received data to /tmp/claude-usage-cache.json.
Run this as a background daemon alongside the Claude Usage menu bar app.
"""

import json
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

USAGE_CACHE = "/tmp/claude-usage-cache.json"
HTTP_PORT = 19222


def iso_to_epoch(iso_str):
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str).timestamp()
    except Exception:
        return None


class UsageReceiver(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/usage":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
            cache = {
                "five_hour": data["five_hour"]["utilization"],
                "five_hour_resets": iso_to_epoch(data["five_hour"].get("resets_at")),
                "seven_day": data["seven_day"]["utilization"],
                "seven_day_resets": iso_to_epoch(data["seven_day"].get("resets_at")),
                "ts": time.time(),
            }
            with open(USAGE_CACHE, "w") as f:
                json.dump(cache, f)
        except Exception:
            pass
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "https://claude.ai")
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "https://claude.ai")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", HTTP_PORT), UsageReceiver)
    print(f"Usage server listening on 127.0.0.1:{HTTP_PORT}")
    server.serve_forever()
