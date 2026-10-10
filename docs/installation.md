# QTS 5.x / TS-253Be installation and validation

QDK QPKG packaging is staged; production release is blocked until the package is built and tested on a real x86_64 QTS 5.x NAS.

- Install QDK on a trusted build machine and run `sh packaging/build.sh`. Confirm generated QPKG contains Python package, HTML, JS, and service script.
- Test QPKG manual install through App Center; confirm start/stop/restart and boot-after-reboot work.
- Python 3.11 at `/opt/bin/python3.11` is preferred, fallback to installed `python3`. Verify required interpreter on NAS.
- Dashboard is intended on port 8778, accessed from trusted LAN or Tailscale only. No public Internet exposure: HTTP API has no authentication.
- Check `/api/status`, physical disk metrics, process read permissions, mount/device mapping, and update discovery.
- Check uninstall/reinstall and upgrade behavior on a backed-up system. Do not publish binary release until real-device validation, checksum, provenance and rollback instructions are available.

Web release checker is read-only: there is **no automatic QPKG installation** yet. An authenticated explicit update endpoint requires verified device-specific QTS installer behavior, integrity verification, and failure recovery.
