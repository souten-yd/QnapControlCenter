"""Lightweight read-only dashboard. localhost-only by default."""
import argparse
import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .monitor import Sampler
from .update import check_latest
from . import installer, lan_update

UI = Path(__file__).with_name("index.html").read_bytes()
JS = Path(__file__).with_name("app.js").read_bytes()
CSS = Path(__file__).with_name("style.css").read_bytes()
ICON = Path(__file__).with_name("apple-touch-icon.png").read_bytes()

class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.samples = deque(maxlen=720)
        self.latest = dict(status="warming_up", disks=[], processes=[])
        self.confirmations = lan_update.OneUseConfirmations()

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
        def log_message(self, fmt, *args):
            # HTTP polling must not generate continuous log writes.
            pass

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                payload, mime = UI, "text/html; charset=utf-8"
            elif self.path == "/apple-touch-icon.png":
                payload, mime = ICON, "image/png"
            elif self.path == "/style.css":
                payload, mime = CSS, "text/css; charset=utf-8"
            elif self.path == "/app.js":
                payload, mime = JS, "text/javascript; charset=utf-8"
            elif self.path == "/api/update-status":
                data=installer.status()
                local, port = self.connection.getsockname()[:2]
                data["lan_available"] = lan_update.allowed_peer(
                    self.client_address[0], local, self.headers.get("Host", ""), expected_port=port
                )
                data["available"] = installer.ready()
                payload,mime=json.dumps(data).encode(),"application/json"
            elif self.path == "/api/status":
                with state.lock:
                    data = dict(latest=state.latest, history=list(state.samples)[-120:])
                payload, mime = json.dumps(data).encode(), "application/json"
            elif self.path == "/api/update":
                try:
                    update = check_latest()
                except (OSError, ValueError, KeyError) as exc:
                    update = dict(error=type(exc).__name__, install_supported=False,
                                  message="GitHub Releases could not be checked.")
                payload, mime = json.dumps(update).encode(), "application/json"
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
        def do_POST(self):
            if self.path not in ("/api/prepare-update", "/api/install-update"):
                self.send_error(404)
                return
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin", "")
            peer = self.client_address[0]
            local, port = self.connection.getsockname()[:2]
            # Trust the real socket only; never use X-Forwarded-For or proxy headers.
            lan_allowed = lan_update.authorized_post(
                peer, local, host, origin,
                self.headers.get("Sec-Fetch-Site", ""),
                self.headers.get("X-QCC-Update-Intent", ""),
                self.headers.get("Content-Type", ""), expected_port=port,
            )
            # Keep the original explicit token path for older clients.
            token_allowed = (
                self.path == "/api/install-update" and
                bool(host) and origin in ("http://" + host, "https://" + host) and
                installer.authenticate(self.headers.get("X-QCC-Admin-Token", ""))
            )
            if not lan_allowed and not token_allowed:
                self.send_error(403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 1024:
                    self.send_error(413)
                    return
                args = json.loads(self.rfile.read(length))
                if not isinstance(args, dict) or not isinstance(args.get("tag"), str):
                    self.send_error(400)
                    return
                tag = args["tag"]
                if not installer.TAG_RE.fullmatch(tag):
                    self.send_error(400)
                    return
                if self.path == "/api/prepare-update":
                    if not lan_allowed or set(args) != {"tag"}:
                        self.send_error(403)
                        return
                    # Only a published, server-discovered release can be prepared.
                    release = check_latest()
                    if release.get("tag") != tag or len(release.get("qpkg", [])) != 1:
                        raise RuntimeError("Release is not the latest published QPKG")
                    if not installer.ready():
                        raise RuntimeError("QTS installer unavailable")
                    nonce = state.confirmations.issue(peer, tag)
                    payload = json.dumps({"tag": tag, "nonce": nonce, "expires_in": 60}).encode()
                    self.send_response(200)
                else:
                    if token_allowed:
                        if set(args) != {"tag"}:
                            self.send_error(400)
                            return
                    else:
                        if (set(args) != {"tag", "nonce"} or
                                not state.confirmations.consume(peer, tag, args.get("nonce"))):
                            self.send_error(403)
                            return
                    payload = json.dumps(installer.start(tag)).encode()
                    self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(payload)
            except (ValueError, RuntimeError, OSError, KeyError) as exc:
                payload = json.dumps({"error": str(exc)[:200]}).encode()
                self.send_response(409)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
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
