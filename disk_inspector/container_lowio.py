"""Strictly scoped QNAP Container Station low-I/O settings control.

Manual Web action only. Two allowlisted QPKG files, exact known snippets,
verified backup, atomic writes; no arbitrary command, paths or shell.
No service lifecycle changes on patch application.
"""
from datetime import datetime
from pathlib import Path
import hashlib
import hmac
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading

GETCFG = "/sbin/getcfg"
QPKG_CONF = "/etc/config/qpkg.conf"
BACKUP_SHARE = Path("/share/Container")
INIT_SCRIPT = Path("/etc/init.d/container-station.sh")
DOCKER_ON = 'DOCKER_OPTS="$DOCKER_OPTS -D"'
DOCKER_OFF = '# DOCKER_OPTS="$DOCKER_OPTS -D"'
FILE_LIMIT = 32768
PATCH_LOCK = threading.Lock()
RESTART_LOCK = threading.Lock()
RESTART_STATE = {"state": "idle", "message": "Not requested"}


class Incompatible(RuntimeError):
    """Fail closed if the QNAP package's expected layout has changed."""


def installed_root():
    run = subprocess.run(
        [GETCFG, "container-station", "Install_Path", "-f", QPKG_CONF],
        capture_output=True, text=True, check=True, timeout=5)
    root = Path(run.stdout.strip())
    if (not root.is_absolute() or root.name != "container-station"
            or root.parent.name != ".qpkg" or not root.is_dir()
            or root.is_symlink()):
        raise Incompatible("Unsupported Container Station installation path")
    return root


def fixed_paths(root):
    root = Path(root)
    if root.name != "container-station" or root.parent.name != ".qpkg":
        raise Incompatible("Unexpected QPKG root")
    return root / "script/run-docker.sh", root / "etc/supervisord.conf"


def read_fixed(path):
    if path.is_symlink():
        raise Incompatible("Refusing symbolic link in QPKG configuration")
    info = path.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_size > FILE_LIMIT):
        raise Incompatible("Configuration file type/size changed")
    raw = path.read_bytes()
    if len(raw) > FILE_LIMIT:
        raise Incompatible("Configuration too large")
    try:
        return raw.decode("utf-8"), info
    except UnicodeError as exc:
        raise Incompatible("Configuration encoding changed") from exc


def patch_docker(text):
    if text.count("exec dockerd $DOCKER_OPTS") != 1:
        raise Incompatible("Docker launch line is not recognized")
    live = re.findall(r"(?m)^" + re.escape(DOCKER_ON) + r"[ \t]*$", text)
    off = re.findall(r"(?m)^" + re.escape(DOCKER_OFF) + r"[ \t]*$", text)
    if len(live) + len(off) != 1:
        raise Incompatible("Docker DEBUG switch changed or duplicated")
    if off:
        return text
    return re.sub(r"(?m)^" + re.escape(DOCKER_ON) + r"(?=[ \t]*$)",
                  DOCKER_OFF, text, count=1)


def patch_supervisor(text):
    sections = list(re.finditer(r"(?m)^\[supervisord\][ \t]*\r?$", text))
    if len(sections) != 1:
        raise Incompatible("Supervisor section is not recognized")
    start = sections[0].end()
    next_section = re.search(r"(?m)^\[", text[start:])
    end = start + next_section.start() if next_section else len(text)
    section = text[start:end]
    levels = re.findall(r"(?im)^[ \t]*loglevel[ \t]*=[ \t]*([^\r\n#;]+)", section)
    if len(levels) == 1 and levels[0].strip().lower() == "warn":
        return text
    if levels:
        raise Incompatible("Existing Supervisor loglevel must be reviewed")
    anchors = list(re.finditer(r"(?m)^logfile_maxbytes=1MB[ \t]*\r?$", section))
    if len(anchors) != 1:
        raise Incompatible("Supervisor logfile anchor changed")
    point = start + anchors[0].end()
    if text.startswith("\r\n", point):
        point += 2
        eol = "\r\n"
    elif text.startswith("\n", point):
        point += 1
        eol = "\n"
    else:
        # A CR may have been matched by the regex above; handle it explicitly.
        if point and text[point-1:point] == "\r" and text.startswith("\n", point):
            point += 1
            eol = "\r\n"
        else:
            raise Incompatible("Supervisor newline layout changed")
    return text[:point] + "loglevel=warn" + eol + text[point:]


def plan(root):
    docker, supervisor = fixed_paths(root)
    originals, replacements, info = {}, {}, {}
    for path, fn in ((docker, patch_docker), (supervisor, patch_supervisor)):
        source, info[path] = read_fixed(path)
        originals[path] = source.encode("utf-8")
        replacements[path] = fn(source).encode("utf-8")
    files = (docker, supervisor)
    fingerprint = hashlib.sha256(
        b"qcc-lowio-v1\0" + b"\0".join(originals[p] for p in files)
    ).hexdigest()
    changed = [p.name for p in files if originals[p] != replacements[p]]
    return files, originals, replacements, info, fingerprint, changed


def current_docker_debug(root):
    names = ("docker.json", "system-docker.json")
    found = {}
    try:
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            try:
                raw = (Path("/proc") / name / "cmdline").read_bytes()
            except OSError:
                continue
            args = [os.fsdecode(x) for x in raw.split(b"\0") if x]
            if not args or Path(args[0]).name != "dockerd":
                continue
            if "--config-file" not in args:
                continue
            index = args.index("--config-file")
            if index + 1 >= len(args):
                continue
            conf = args[index + 1]
            for expected in names:
                if conf == str(root / "etc" / expected):
                    found[expected] = {"debug": "-D" in args or "--debug" in args,
                                       "running": True}
        return {name: found.get(name, {"running": False}) for name in names}
    except OSError:
        return {name: {"running": False} for name in names}


def restart_available():
    # Only a fixed QTS service entrypoint; no config-derived executable path.
    return (INIT_SCRIPT.is_file() and not INIT_SCRIPT.is_symlink()
            and os.access(INIT_SCRIPT, os.X_OK) and os.geteuid() == 0)


def inspect(root=None):
    try:
        root = installed_root() if root is None else Path(root)
        files, old, new, meta, fingerprint, changed = plan(root)
        running = current_docker_debug(root)
        restart_needed = not changed and any(
            v.get("debug") for v in running.values())
        return {"state": "needs_apply" if changed else
                         "restart_required" if restart_needed else "applied",
                "needs_apply": bool(changed),
                "restart_required": restart_needed,
                "changes": changed, "fingerprint": fingerprint,
                "runtime": running,
                "writable": os.geteuid() == 0 and all(
                    os.access(p.parent, os.W_OK) for p in files),
                "restart_available": restart_available(),
                "message": "Apply quiet-log settings" if changed else
                           "Restart Container Station to activate changes"
                           if restart_needed else "Quiet-log settings are present"}
    except (OSError, ValueError, subprocess.SubprocessError, Incompatible) as exc:
        return {"state": "unsupported", "needs_apply": False,
                "writable": False, "restart_available": False,
                "message": str(exc)[:180]}


def atomic_write(path, raw, info):
    fd, temp = tempfile.mkstemp(prefix=".qcc-lowio-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, stat.S_IMODE(info.st_mode))
        os.chown(temp, info.st_uid, info.st_gid)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def verified_backup(files, root, parent):
    parent = Path(parent)
    # Allow /share/Container QTS symlink, but only onto the same QPKG volume.
    if not parent.is_dir() or parent.resolve().parent != root.parent.parent.resolve():
        raise Incompatible("Backup share must be on Container Station's volume")
    backup = Path(tempfile.mkdtemp(
        prefix="ContainerStation-lowio-backup-" +
               datetime.now().strftime("%Y%m%d-") + "-", dir=str(parent)))
    os.chmod(backup, 0o700)
    for path in files:
        dest = backup / path.name
        shutil.copy2(path, dest, follow_symlinks=False)
        meta = path.stat()
        os.chown(dest, meta.st_uid, meta.st_gid)
        if dest.read_bytes() != path.read_bytes():
            raise OSError("Backup verification failed")
    return backup


def apply(fingerprint, *, root=None, backup_parent=None):
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("Invalid configuration fingerprint")
    if os.geteuid() != 0:
        raise PermissionError("QnapControlCenter does not have QTS admin permissions")
    with PATCH_LOCK:
        root = installed_root() if root is None else Path(root)
        files, old, new, info, actual, changed = plan(root)
        if not hmac.compare_digest(actual, fingerprint):
            raise Incompatible("Configuration changed; inspect again")
        if not changed:
            return {"state": "applied", "message": "Already applied, no changes"}
        # Always preserve both originals, including permissions, before modifying.
        backup = verified_backup(
            files, root, BACKUP_SHARE if backup_parent is None else backup_parent)
        modified = []
        try:
            if any(p.is_symlink() or p.read_bytes() != old[p] for p in files):
                raise Incompatible("Configuration modified during patch preparation")
            # Reject changed shell syntax before writing to the installed service.
            code = subprocess.run(["/bin/sh", "-n"], input=new[files[0]],
                                  capture_output=True, timeout=5)
            if code.returncode:
                raise Incompatible("Patched Docker shell syntax is invalid")
            for path in files:
                if old[path] != new[path]:
                    atomic_write(path, new[path], info[path])
                    modified.append(path)
            plan(root)  # Post-write compatibility verification.
        except BaseException:
            for path in reversed(modified):
                atomic_write(path, old[path], info[path])
            raise
        return {"state": "applied", "message":
                "Patched files; a Container Station restart is required",
                "backup": str(backup), "changed": changed,
                "restart_performed": False}


def restart_status():
    with RESTART_LOCK:
        return dict(RESTART_STATE)


def request_restart():
    if not restart_available():
        raise RuntimeError("QTS Container Station restart script unavailable")
    plan(installed_root())  # Refuse unsupported package layouts.
    if inspect().get("needs_apply"):
        raise RuntimeError("Apply low-I/O patch before restart")
    with RESTART_LOCK:
        if RESTART_STATE["state"] == "running":
            raise RuntimeError("Container Station restart is already in progress")
        RESTART_STATE.update(state="running",
                             message="Restarting Container Station; containers may stop")
    def worker():
        try:
            result = subprocess.run(
                [str(INIT_SCRIPT), "restart"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=180, check=False)
            data = ({"state": "complete", "message":
                     "QTS restart script completed; verify containers and Docker"}
                    if result.returncode == 0 else
                    {"state": "error", "message":
                     "QTS restart returned exit code %d" % result.returncode})
        except (OSError, subprocess.TimeoutExpired) as exc:
            data = {"state": "error", "message": type(exc).__name__}
        with RESTART_LOCK:
            RESTART_STATE.update(data)
    threading.Thread(target=worker, daemon=True).start()
    return {"state": "running", "message": "Container Station restart requested"}
