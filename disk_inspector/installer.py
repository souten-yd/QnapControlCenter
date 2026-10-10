"""Restricted QPKG update preparation and one-shot installer worker.

No arbitrary URL, package path, command or shell interpolation is accepted.
A per-install admin token is required; disabled without QTS qpkg_cli.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen

REPO = "souten-yd/QnapControlCenter"
API = "https://api.github.com/repos/" + REPO + "/releases/tags/"
TOKEN_FILE = Path("/var/run/qnapcontrolcenter-update-token")
STATUS_FILE = Path("/var/run/qnapcontrolcenter-update-status.json")
MAX_QPKG = 128 * 1024 * 1024
MAX_CHECKSUM = 256 * 1024
TAG_RE = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(?:-rc[0-9]+)?$")
ASSET_RE = re.compile(r"^QnapControlCenter.*\.qpkg$", re.I)

def ready():
    cli = shutil.which("qpkg_cli")
    return bool(cli and Path(cli).is_file() and TOKEN_FILE.is_file())

def authenticate(token):
    try:
        expected = TOKEN_FILE.read_text().strip()
    except OSError:
        return False
    return bool(token and len(token) <= 256 and hmac.compare_digest(token, expected))

def _read_url(url, maximum):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ("api.github.com", "github.com", "release-assets.githubusercontent.com"):
        raise ValueError("Unexpected download host")
    request = Request(url, headers={"User-Agent": "QnapControlCenter-Updater", "Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=30) as response:
        final = urlparse(response.geturl())
        if final.scheme != "https" or final.hostname not in ("api.github.com", "github.com", "release-assets.githubusercontent.com"):
            raise ValueError("Untrusted redirect host")
        if int(response.headers.get("Content-Length", 0)) > maximum:
            raise ValueError("File too large")
        payload = response.read(maximum + 1)
    if len(payload) > maximum:
        raise ValueError("File too large")
    return payload

def release(tag):
    if not TAG_RE.fullmatch(tag):
        raise ValueError("Invalid release tag")
    data = json.loads(_read_url(API + tag, MAX_CHECKSUM))
    if data.get("draft") or data.get("tag_name") != tag:
        raise ValueError("Release not published")
    assets = data.get("assets", [])
    qpkgs = [a for a in assets if ASSET_RE.fullmatch(a.get("name", ""))]
    checksums = [a for a in assets if a.get("name") == "SHA256SUMS"]
    if len(qpkgs) != 1 or len(checksums) != 1:
        raise ValueError("Expected one QPKG and SHA256SUMS")
    prefix = "https://github.com/" + REPO + "/releases/download/" + tag + "/"
    if any(not a.get("browser_download_url", "").startswith(prefix) for a in qpkgs + checksums):
        raise ValueError("Asset URL mismatch")
    if qpkgs[0].get("size", MAX_QPKG + 1) > MAX_QPKG:
        raise ValueError("Package too large")
    return qpkgs[0], checksums[0]

def stage_verified(tag):
    pkg, sums = release(tag)
    digest_lines = _read_url(sums["browser_download_url"], MAX_CHECKSUM).decode("utf-8").splitlines()
    expected = []
    for line in digest_lines:
        parts = line.strip().split()
        if len(parts) == 2 and parts[1].lstrip("*") == pkg["name"] and re.fullmatch("[a-fA-F0-9]{64}", parts[0]):
            expected.append(parts[0].lower())
    if len(expected) != 1:
        raise ValueError("Missing unique package SHA256")
    body = _read_url(pkg["browser_download_url"], MAX_QPKG)
    if len(body) != pkg["size"]:
        raise ValueError("Package size mismatch")
    if hashlib.sha256(body).hexdigest() != expected[0]:
        raise ValueError("SHA256 mismatch")
    folder = tempfile.mkdtemp(prefix="qcc-update-", dir="/tmp")
    target = Path(folder) / "QnapControlCenter.qpkg"
    target.write_bytes(body)
    os.chmod(target, 0o600)
    return target

def write_status(state, message):
    STATUS_FILE.write_text(json.dumps({"state": state, "message": message}, ensure_ascii=False))

def worker(tag):
    target = None
    try:
        write_status("downloading", "Downloading and verifying QPKG")
        target = stage_verified(tag)
        cli = shutil.which("qpkg_cli")
        if not cli:
            raise RuntimeError("QTS qpkg_cli not available")
        write_status("installing", "Validated QPKG; requesting QTS installation")
        # Fixed argument vector; no request-supplied CLI options.
        proc = subprocess.run([cli, "-m", str(target)], timeout=300, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError("QTS installer failed (exit %s)" % proc.returncode)
        write_status("restarting", "QTS installer returned success; confirm version after service restart")
    except Exception as exc:
        write_status("error", "%s: %s" % (type(exc).__name__, str(exc)[:180]))
    finally:
        if target:
            try:
                target.unlink(missing_ok=True)
                target.parent.rmdir()
            except OSError:
                pass

def start(tag):
    if not ready():
        raise RuntimeError("Updater unavailable: qpkg_cli or admin token missing")
    if STATUS_FILE.exists():
        try:
            state = json.loads(STATUS_FILE.read_text()).get("state")
            if state in ("downloading", "installing"):
                raise RuntimeError("An update is already running")
        except ValueError:
            pass
    # Launch independent child so QTS can stop/restart the HTTP service while installing.
    import sys
    import subprocess
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
    subprocess.Popen([sys.executable, "-B", "-m", "disk_inspector.installer", "--apply", tag],
                     env=env, cwd="/", stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, close_fds=True)
    return {"state": "starting", "message": "Update requested"}

def status():
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text())
        except (OSError, ValueError):
            pass
    return {"state": "idle", "message": "No update in progress"}

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3 or sys.argv[1] != "--apply" or not TAG_RE.fullmatch(sys.argv[2]):
        raise SystemExit(2)
    worker(sys.argv[2])
