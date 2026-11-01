"""Explicit, single-flight update of an official, SHA-256-verified QPKG.

The worker runs from a private RAM job directory OUTSIDE the QPKG being replaced.
Only server-discovered GitHub releases are accepted; no client paths/commands.
"""
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import urllib.request

REPO = "souten-yd/QnapControlCenter"
API = "https://api.github.com/repos/" + REPO + "/releases/tags/"
TOKEN_FILE = Path("/var/run/qnapcontrolcenter-update-token")
STATUS_FILE = Path("/var/run/qnapcontrolcenter-update-status.json")
LOCK_FILE = Path("/var/run/qnapcontrolcenter-update.lock")
LOG_FILE = Path("/var/run/qnapcontrolcenter-update.log")
GETCFG = "/sbin/getcfg"
QPKG_CONF = "/etc/config/qpkg.conf"
RAM_ROOT = "/dev/shm"
MAX_QPKG = 128 * 1024 * 1024
MAX_CHECKSUM = 256 * 1024
TAG_RE = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(?:-rc[0-9]+)?$")
ASSET_RE = re.compile(r"^QnapControlCenter_[0-9]+\.[0-9]+\.[0-9]+_x86_64\.qpkg$")
ACTIVE = frozenset(("queued", "checking", "downloading", "stopping", "installing", "verifying"))
VERIFY_SECONDS = 120


def version(tag):
    if not isinstance(tag, str) or not TAG_RE.fullmatch(tag):
        raise ValueError("Invalid release tag")
    return tuple(int(x) for x in tag[1:].split("-")[0].split("."))


def getcfg(field):
    return subprocess.check_output(
        [GETCFG, "QnapControlCenter", field, "-d", "", "-f", QPKG_CONF],
        text=True, timeout=5).strip()


def environment():
    if os.geteuid() != 0:
        raise ValueError("Updater requires QTS QPKG administrator privileges")
    if not Path(GETCFG).is_file() or not Path(QPKG_CONF).is_file():
        raise ValueError("QTS QPKG configuration unavailable")
    base = getcfg("Install_Path")
    if not base or Path(base).resolve().name != "QnapControlCenter":
        raise ValueError("QnapControlCenter QPKG registration not found")
    if not (Path(base) / "QnapControlCenter.sh").is_file():
        raise ValueError("QnapControlCenter QPKG service script missing")
    if getcfg("Enable").upper() != "TRUE":
        raise ValueError("QnapControlCenter QPKG is disabled")
    if not Path("/bin/sh").is_file() or not os.path.ismount(RAM_ROOT):
        raise ValueError("QTS shell or RAM staging mount unavailable")
    return Path(base).resolve()


def ready():
    try:
        environment()
        return True
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def unavailable_reason():
    try:
        environment()
        return ""
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return str(error)[:180]


def authenticate(token):
    try:
        expected = TOKEN_FILE.read_text().strip()
    except OSError:
        return False
    return bool(token and len(token) <= 256 and hmac.compare_digest(token, expected))


def _read_url(url, maximum):
    parsed = urlparse(url)
    if (parsed.scheme != "https" or
            parsed.hostname not in ("api.github.com", "github.com", "release-assets.githubusercontent.com")):
        raise ValueError("Unexpected download host")
    request = Request(url, headers={
        "User-Agent": "QnapControlCenter-Updater/0.2",
        "Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=30) as response:
        final = urlparse(response.geturl())
        if (final.scheme != "https" or
                final.hostname not in ("api.github.com", "github.com", "release-assets.githubusercontent.com")):
            raise ValueError("Untrusted redirect host")
        content_length = response.headers.get("Content-Length")
        if content_length is not None and int(content_length) > maximum:
            raise ValueError("File too large")
        payload = response.read(maximum + 1)
    if len(payload) > maximum:
        raise ValueError("File too large")
    return payload


def release(tag):
    numeric_version = version(tag)
    data = json.loads(_read_url(API + tag, MAX_CHECKSUM))
    if data.get("draft") or data.get("tag_name") != tag:
        raise ValueError("Release is not published")
    assets = data.get("assets", [])
    pkg_name = "QnapControlCenter_" + ".".join(map(str, numeric_version)) + "_x86_64.qpkg"
    qpkgs = [a for a in assets if a.get("name") == pkg_name]
    checksums = [a for a in assets if a.get("name") == "SHA256SUMS"]
    if len(qpkgs) != 1 or len(checksums) != 1:
        raise ValueError("Expected matching x86_64 QPKG and SHA256SUMS")
    prefix = "https://github.com/" + REPO + "/releases/download/" + tag + "/"
    for asset in qpkgs + checksums:
        if asset.get("browser_download_url") != prefix + asset["name"]:
            raise ValueError("Asset URL mismatch")
    size = qpkgs[0].get("size")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_QPKG:
        raise ValueError("Invalid package size")
    return qpkgs[0], checksums[0]


def stage_verified(tag, folder):
    pkg, sums = release(tag)
    digest_lines = _read_url(sums["browser_download_url"], MAX_CHECKSUM).decode("utf-8").splitlines()
    expected = []
    for line in digest_lines:
        parts = line.strip().split()
        if (len(parts) == 2 and parts[1].lstrip("*") == pkg["name"] and
                re.fullmatch(r"[a-fA-F0-9]{64}", parts[0])):
            expected.append(parts[0].lower())
    if len(expected) != 1:
        raise ValueError("Missing unique package SHA256")
    github_digest = pkg.get("digest")
    if github_digest and github_digest != "sha256:" + expected[0]:
        raise ValueError("GitHub asset digest mismatch")
    if shutil.disk_usage(folder).free < pkg["size"] + 8 * 1024 * 1024:
        raise RuntimeError("Insufficient RAM for upgrade")
    body = _read_url(pkg["browser_download_url"], MAX_QPKG)
    if len(body) != pkg["size"] or hashlib.sha256(body).hexdigest() != expected[0]:
        raise ValueError("QPKG size or SHA256 mismatch")
    target = Path(folder) / pkg["name"]
    with target.open("xb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    target.chmod(0o600)
    return target


def _read_status():
    try:
        value = json.loads(STATUS_FILE.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_status(state, message, **extra):
    value = dict(_read_status(), state=state, message=message,
                 updated_at=time.time(), **extra)
    temp = STATUS_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False))
    os.replace(temp, STATUS_FILE)
    print(state + ": " + message, flush=True)


def _lock():
    fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise RuntimeError("Another update is already running") from None
    return fd


def status():
    current = _read_status()
    try:
        fd = _lock()
    except RuntimeError:
        busy = True
    else:
        busy = False
        os.close(fd)
        if current.get("state") in ACTIVE:
            write_status("error", "Update worker exited before completion; inspect the update log")
            current = _read_status()
    return dict(current or {"state": "idle", "message": "No update in progress"}, busy=busy)


def log_tail():
    try:
        with LOG_FILE.open("rb") as file:
            file.seek(0, 2)
            file.seek(max(0, file.tell() - 16000))
            return file.read(16000).decode("utf-8", errors="replace")
    except OSError:
        return ""


def start(tag):
    version(tag)
    base = environment()
    if version(tag) < tuple(map(int, getcfg("Version").split("."))):
        raise ValueError("Downgrade refused")
    fd = _lock()
    job = None
    try:
        # Snapshot the worker outside the QPKG tree BEFORE allowing QTS to replace it.
        job = Path(tempfile.mkdtemp(prefix="qcc-update-", dir=RAM_ROOT))
        job.chmod(0o700)
        copied = job / "worker.py"
        shutil.copyfile(__file__, copied)
        # A dedicated per-job log in volatile /var/run survives Web service restart.
        with LOG_FILE.open("wb") as log:
            log.write(b"QnapControlCenter update starting\n")
        write_status("queued", "Update request accepted", tag=tag, started_at=time.time())
        with LOG_FILE.open("ab") as log:
            subprocess.Popen(
                [sys.executable, "-B", str(copied), "--apply", tag,
                 "--job", str(job), "--lock-fd", str(fd), "--install-root", str(base)],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                env=dict(os.environ), cwd=str(job),
                start_new_session=True, close_fds=True, pass_fds=(fd,))
    except Exception:
        write_status("error", "Could not launch detached update worker")
        if job is not None:
            shutil.rmtree(job, ignore_errors=True)
        raise
    finally:
        os.close(fd)
    return {"state": "queued", "message": "Update worker started"}


def wait_for_version(tag, timeout=VERIFY_SECONDS):
    expected = ".".join(map(str, version(tag)))
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if getcfg("Version") == expected and getcfg("Enable").upper() == "TRUE":
                with client.open("http://127.0.0.1:8778/api/runtime", timeout=3) as response:
                    running = json.load(response)
                if running.get("running_version") == expected and running.get("pid"):
                    return
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        time.sleep(2)
    raise RuntimeError("Installed version / Web runtime did not become healthy within 120s")


def worker(tag, job, lock_fd, install_root):
    # Inherited flock stays held across server stop/restart and QPKG replacement.
    if os.fstat(lock_fd).st_ino != LOCK_FILE.stat().st_ino:
        raise RuntimeError("Worker lock identity mismatch")
    os.set_inheritable(lock_fd, False)
    os.umask(0o077)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    package = None
    installer_finished = True
    stopped = False
    try:
        write_status("checking", "Checking published QPKG and installed registration")
        if environment() != Path(install_root):
            raise ValueError("Installed QPKG root changed; refusing update")
        if version(tag) < tuple(map(int, getcfg("Version").split("."))):
            raise ValueError("Downgrade refused")
        write_status("downloading", "Downloading and verifying official SHA-256 QPKG")
        package = stage_verified(tag, job)
        write_status("stopping", "Stopping current Web service before upgrade")
        subprocess.run(["/bin/sh", str(Path(install_root) / "QnapControlCenter.sh"), "stop"],
                       check=True, stdin=subprocess.DEVNULL, timeout=30)
        stopped = True
        write_status("installing", "Installing verified QPKG; Web may temporarily disconnect")
        # QDK QPKG is a shell installer; QTS qpkg_cli -m is not a general QPKG install API.
        # This matches the working QnapSelfCare updater. No user-provided shell code.
        installer = subprocess.Popen(
            ["/bin/sh", str(package)], stdin=subprocess.DEVNULL,
            cwd=str(job), start_new_session=True, close_fds=True,
            env=dict(os.environ, QINSTALL_PATH=str(Path(install_root).parent)))
        installer_finished = False
        try:
            returncode = installer.wait(timeout=600)
            installer_finished = True
        except subprocess.TimeoutExpired:
            # Do not terminate QDK mid-install; keep worker/lock alive until it exits.
            write_status("installing", "QPKG installer running longer than expected; waiting")
            returncode = installer.wait()
            installer_finished = True
        if returncode not in (0, 10):
            raise RuntimeError("QPKG installer exited with code " + str(returncode))
        write_status("verifying", "Checking QTS registration and running Web version")
        wait_for_version(tag)
        write_status("success", tag + " installed and Web service verified", finished_at=time.time())
    except Exception as error:
        write_status("error", type(error).__name__ + ": " + str(error)[:180],
                     finished_at=time.time())
        if stopped and installer_finished:
            try:
                if getcfg("Enable").upper() == "TRUE":
                    subprocess.run(["/bin/sh", str(Path(install_root) / "QnapControlCenter.sh"), "start"],
                                   timeout=25, stdin=subprocess.DEVNULL, check=True)
            except (OSError, subprocess.SubprocessError) as recovery:
                print("Recovery start failed:", recovery, flush=True)
        return 1
    finally:
        if package is not None:
            try:
                package.unlink(missing_ok=True)
            except OSError:
                pass
        # Only the worker's private, fixed-prefix RAM job is removed.
        if str(job).startswith(RAM_ROOT + "/qcc-update-"):
            shutil.rmtree(job, ignore_errors=True)
        os.close(lock_fd)
    return 0


if __name__ == "__main__":
    if (len(sys.argv) != 9 or sys.argv[1] != "--apply" or
            sys.argv[3] != "--job" or sys.argv[5] != "--lock-fd" or
            sys.argv[7] != "--install-root"):
        raise SystemExit(2)
    sys.exit(worker(sys.argv[2], Path(sys.argv[4]),
                    int(sys.argv[6]), sys.argv[8]))
