"""Tiny in-memory ntfy look-alike for local testing (publish, poll, stream)."""
import json
import re
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MESSAGES = []                     # list of event dicts
COND = threading.Condition()


def add(topic, message, extra=None):
    ev = {"id": secrets.token_hex(6), "time": int(time.time()), "event": "message",
          "topic": topic, "message": message, **(extra or {})}
    with COND:
        MESSAGES.append(ev)
        COND.notify_all()
    return ev


def since_filter(since):
    if not since:
        return lambda ev: True
    m = re.fullmatch(r"(\d+)([smh])", since)
    if m:
        cutoff = time.time() - int(m[1]) * {"s": 1, "m": 60, "h": 3600}[m[2]]
        return lambda ev: ev["time"] >= cutoff
    ids = [e["id"] for e in MESSAGES]
    idx = ids.index(since) if since in ids else -1
    keep = {e["id"] for e in MESSAGES[idx + 1:]}
    return lambda ev: ev["id"] in keep


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        path = urlparse(self.path).path.strip("/")
        if not path:
            data = json.loads(body)
            topic = data.pop("topic")
            ev = add(topic, data.pop("message", ""), data)
        else:
            ev = add(path, body)
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(ev).encode())

    def do_GET(self):
        u = urlparse(self.path)
        m = re.fullmatch(r"/([\w-]+)/json", u.path)
        if not m:
            self.send_response(404); self.end_headers(); return
        topic, q = m[1], parse_qs(u.query)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if q.get("poll"):
            f = since_filter(q.get("since", [""])[0])
            with COND:
                out = [e for e in MESSAGES if e["topic"] == topic and f(e)]
            self.wfile.write("".join(json.dumps(e) + "\n" for e in out).encode())
            return
        self.wfile.write(b'{"event":"open"}\n'); self.wfile.flush()
        seen = len(MESSAGES)
        try:
            while True:
                with COND:
                    COND.wait(timeout=10)
                    new, seen = MESSAGES[seen:], len(MESSAGES)
                for e in new:
                    if e["topic"] == topic:
                        self.wfile.write((json.dumps(e) + "\n").encode())
                self.wfile.write(b'{"event":"keepalive"}\n'); self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
