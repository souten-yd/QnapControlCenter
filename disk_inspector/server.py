"""Lightweight read-only dashboard. localhost-only by default."""
import argparse
import os
import json
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .monitor import Sampler
from .write_log import RollingWriteLog
from .update import check_latest
from . import installer, lan_update, container_lowio

UI = Path(__file__).with_name("index.html").read_bytes()
JS = Path(__file__).with_name("app.js").read_bytes()
REPORT_JS = Path(__file__).with_name("write_report.js").read_bytes()
CSS = Path(__file__).with_name("style.css").read_bytes()
ICON = Path(__file__).with_name("apple-touch-icon.png").read_bytes()

def read_build_info():
    """Startup-only package metadata; no repeated filesystem reads during polling."""
    try:
        data = json.loads(Path(__file__).with_name("build_info.json").read_text())
        if isinstance(data, dict) and isinstance(data.get("version"), str):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return {"version": "development", "build_id": "development", "commit": "local",
            "features": ["write_diagnostics", "lan_updater"]}

BUILD_INFO = read_build_info()
RUNTIME_STARTED_AT = int(time.time())

def runtime_info():
    return {
        "running_version": BUILD_INFO.get("version", "development"),
        "build_id": BUILD_INFO.get("build_id", "development"),
        "commit": BUILD_INFO.get("commit", "local"),
        "started_at": RUNTIME_STARTED_AT,
        "pid": os.getpid(),
        "features": {"write_diagnostics": True, "lan_updater": True},
        "diagnostics_endpoint": "/api/write-log",
    }

class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.samples = deque(maxlen=60)
        self.write_log = RollingWriteLog()
        self.latest = dict(status="warming_up", disks=[], processes=[])
        self.confirmations = lan_update.OneUseConfirmations()
        self.lowio_confirms = lan_update.OneUseConfirmations()

    def collect(self, interval):
        sampler = Sampler()
        while True:
            try:
                sample = sampler.sample()
            except (OSError, ValueError) as exc:
                sample = dict(status="error", error=type(exc).__name__, disks=[], processes=[])
            # Write events are transient and never stored in the regular status ring.
            with self.lock:
                self.write_log.record(sample)
                public_sample = dict(sample)
                public_sample.pop("write_events", None)
                self.latest = public_sample
                self.samples.append(public_sample)
            time.sleep(interval)

def local_admin_connection(peer, local, host, port):
    """Additional confinement: only an actual NAS loopback socket."""
    from ipaddress import ip_address
    try:
        return (ip_address(peer).is_loopback and ip_address(local).is_loopback
                and lan_update.allowed_peer(peer, local, host, expected_port=port))
    except ValueError:
        return False


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
            elif self.path == "/write_report.js":
                payload, mime = REPORT_JS, "text/javascript; charset=utf-8"
            elif self.path == "/api/runtime":
                payload, mime = json.dumps(runtime_info()).encode(), "application/json"
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
            elif self.path == "/api/write-log":
                with state.lock:
                    data = state.write_log.snapshot()
                payload, mime = json.dumps(data).encode(), "application/json"
            elif self.path == "/api/container-lowio":
                local, port = self.connection.getsockname()[:2]
                data = container_lowio.inspect()
                data["lan_available"] = lan_update.allowed_peer(
                    self.client_address[0], local, self.headers.get("Host", ""),
                    expected_port=port)
                data["restart_status"] = container_lowio.restart_status()
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
            self.send_header("Cache-Control", "no-store, max-age=0, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'")
            self.end_headers()
            self.wfile.write(payload)
        def do_POST(self):
            if self.path in ("/api/container-lowio/prepare",
                             "/api/container-lowio/apply",
                             "/api/container-lowio/prepare-restart",
                             "/api/container-lowio/restart"):
                self._post_container_lowio()
                return
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
            # Legacy token path stays for backward-compatible clients; LAN Web UI never needs one.
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
        def _post_container_lowio(self):
            # Same trusted-LAN model as the existing official updater.
            # This is NOT QTS administrator identity verification.
            peer = self.client_address[0]
            local, port = self.connection.getsockname()[:2]
            host = self.headers.get("Host", "")
            if not lan_update.authorized_post(
                    peer, local, host, self.headers.get("Origin", ""),
                    self.headers.get("Sec-Fetch-Site", ""),
                    self.headers.get("X-QCC-Lowio-Intent", ""),
                    self.headers.get("Content-Type", ""), expected_port=port):
                self.send_error(403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 2 or length > 512:
                    self.send_error(413)
                    return
                args = json.loads(self.rfile.read(length))
                if not isinstance(args, dict):
                    self.send_error(400)
                    return
                if self.path == "/api/container-lowio/prepare":
                    if args:
                        self.send_error(400)
                        return
                    current = container_lowio.inspect()
                    if (not current.get("writable") or
                            not current.get("needs_apply")):
                        raise RuntimeError(current.get("message", "Patch unavailable"))
                    fingerprint = current["fingerprint"]
                    nonce = state.lowio_confirms.issue(peer, fingerprint)
                    output = {"fingerprint": fingerprint, "nonce": nonce,
                              "changes": current["changes"], "expires_in": 60}
                    code = 200
                elif self.path == "/api/container-lowio/apply":
                    if set(args) != {"fingerprint", "nonce"}:
                        self.send_error(400)
                        return
                    fingerprint = args["fingerprint"]
                    if (not isinstance(fingerprint, str) or
                            not state.lowio_confirms.consume(
                                peer, fingerprint, args["nonce"])):
                        self.send_error(403)
                        return
                    output = container_lowio.apply(fingerprint)
                    code = 200
                elif self.path == "/api/container-lowio/prepare-restart":
                    if args:
                        self.send_error(400)
                        return
                    current = container_lowio.inspect()
                    if (not current.get("restart_available")
                            or current.get("state") == "unsupported"
                            or current.get("needs_apply")):
                        raise RuntimeError("Container Station restart is unavailable")
                    nonce = state.lowio_confirms.issue(peer, "container-station-restart")
                    output = {"nonce": nonce, "expires_in": 60}
                    code = 200
                else:
                    if (set(args) != {"nonce"} or not state.lowio_confirms.consume(
                            peer, "container-station-restart", args["nonce"])):
                        self.send_error(403)
                        return
                    output = container_lowio.request_restart()
                    code = 202
                self._lowio_json(code, output)
            except (OSError, ValueError, KeyError, RuntimeError,
                    PermissionError, subprocess.SubprocessError) as exc:
                self._lowio_json(409, {"error": str(exc)[:200]})

        def _lowio_json(self, status_code, result):
            payload = json.dumps(result).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
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
