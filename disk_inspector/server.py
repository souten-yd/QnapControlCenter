"""Lightweight read-only dashboard. localhost-only by default."""
import argparse
import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .monitor import Sampler

UI = Path(__file__).with_name("index.html").read_bytes()

class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.samples = deque(maxlen=720)
        self.latest = dict(status="warming_up", disks=[], processes=[])

    def collect(self, interval):
        sampler = Sampler()
        while True:
            try:
                sample = sampler.sample()
            except (OSError, ValueError) as exc:
                sample = dict(status="error", error=type(exc).__name__, disks=[], processes=[])
            with self.lock:
                self.latest = sample
                self.samples.append(sample)
            time.sleep(interval)

def handler_factory(state):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/", "/index.html"):
                payload, mime = UI, "text/html; charset=utf-8"
            elif self.path == "/api/status":
                with state.lock:
                    data = dict(latest=state.latest, history=list(state.samples)[-120:])
                payload, mime = json.dumps(data).encode(), "application/json"
            elif self.path == "/api/update":
                payload, mime = json.dumps(dict(supported=False,
                  message="Manual QPKG update required until signed release validation and QTS installer integration are verified.")).encode(), "application/json"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'")
            self.end_headers()
            self.wfile.write(payload)
    return Handler

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8778)
    parser.add_argument("--interval", type=float, default=5)
    args = parser.parse_args()
    if args.interval < 1:
        parser.error("--interval must be >= 1 second")
    state = State()
    threading.Thread(target=state.collect, args=(args.interval,), daemon=True).start()
    ThreadingHTTPServer((args.host, args.port), handler_factory(state)).serve_forever()

if __name__ == "__main__":
    main()
