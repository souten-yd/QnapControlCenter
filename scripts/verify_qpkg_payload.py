"""Read-only inspection of QDK 2.5.x self-extracting QPKG build output."""
import io
import json
import re
import sys
import tarfile
from pathlib import Path

def verify_qpkg(path):
    path = Path(path)
    payload = path.read_bytes()
    header = payload[:8192].split(b"\x00", 1)[0]
    script_len = re.search(rb"script_len=(\d+)", header)
    control_len = re.search(rb"offset=\$\(/usr/bin/expr \$script_len \+ (\d+)\)", header)
    data_len = re.search(rb"f.seek\((\d+)\)", header)
    if not (script_len and control_len and data_len):
        raise ValueError("Unsupported QDK package layout; cannot validate payload")
    start = int(script_len[1]) + int(control_len[1])
    end = start + int(data_len[1])
    if end > len(payload):
        raise ValueError("QDK data archive truncated")
    with tarfile.open(fileobj=io.BytesIO(payload[start:end]), mode="r:gz") as archive:
        members = {member.name.removeprefix("./"): member for member in archive.getmembers()}
        required = (
            "disk_inspector/index.html",
            "disk_inspector/app.js",
            "disk_inspector/server.py",
            "disk_inspector/write_log.py",
            "disk_inspector/build_info.json",
            "QnapControlCenter.sh",
        )
        missing = [name for name in required if name not in members]
        if missing:
            raise ValueError("QPKG payload missing: " + ", ".join(missing))
        def load(name):
            return archive.extractfile(members[name]).read()
        html = load("disk_inspector/index.html").decode("utf-8")
        js = load("disk_inspector/app.js").decode("utf-8")
        server = load("disk_inspector/server.py").decode("utf-8")
        info = json.loads(load("disk_inspector/build_info.json"))
        if ('update-token' in html or 'manual-token' in html):
            raise ValueError("QPKG must not ask LAN users for an admin token")
        if ('href="#write-log"' not in html or 'id="write-log"' not in html or
                'id="open-write-log"' not in html or
                "/api/write-log" not in js or "scrollIntoView(" not in js or
                "/api/write-log" not in server or
                "/api/runtime" not in server):
            raise ValueError("QPKG write diagnostics UI/API contract is missing")
        expected = re.search(r"QnapControlCenter_([0-9]+(?:[.][0-9]+){2})_", path.name)
        if not expected or info.get("version") != expected[1]:
            raise ValueError("QPKG filename and bundled runtime version differ")
    return info

def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: verify_qpkg_payload.py <file.qpkg>")
    print(json.dumps(verify_qpkg(sys.argv[1]), sort_keys=True))

if __name__ == "__main__":
    main()
