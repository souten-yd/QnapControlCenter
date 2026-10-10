# QTS 5.x / TS-253Be installation and validation

QDK QPKG packaging is staged; production release is blocked until the package is built and tested on a real x86_64 QTS 5.x NAS.

- Install QDK on a trusted build machine and run `sh packaging/build.sh`. Confirm generated QPKG contains Python package, HTML, JS, and service script.
- Test QPKG manual install through App Center; confirm start/stop/restart and boot-after-reboot work.
- Python 3.11 at `/opt/bin/python3.11` is preferred, fallback to installed `python3`. Verify required interpreter on NAS.
- Dashboard is intended on port 8778, accessed from trusted LAN or Tailscale only. No public Internet exposure: HTTP API has no authentication.
- Check `/api/status`, physical disk metrics, process read permissions, mount/device mapping, and update discovery.
- Check uninstall/reinstall and upgrade behavior on a backed-up system. Do not publish binary release until real-device validation, checksum, provenance and rollback instructions are available.

Web release checker is read-only: there is **no automatic QPKG installation** yet. An authenticated explicit update endpoint requires verified device-specific QTS installer behavior, integrity verification, and failure recovery.


## ERR_CONNECTION_FAILED troubleshooting
QTS App Center Open should target `http://NAS-IP:8778/` with `QPKG_WEBUI=/`, `QPKG_WEB_PORT=8778`, `QPKG_WEB_SSL_PORT=-2`.
After installing QPKG v0.1.2 or later, check service status in App Center; SSH diagnostics:

```sh
cat /var/run/qnapcontrolcenter-startup.log
grep -A 20 '^\[QnapControlCenter\]' /etc/config/qpkg.conf
netstat -lnt 2>/dev/null | grep ':8778'
curl -v --max-time 5 http://127.0.0.1:8778/api/status
ls -l /opt/bin/python3.11 /usr/bin/python3 2>/dev/null
```

The start script logs errors in `/var/run` (tmpfs, cleared on reboot), checks Python and package files, waits for HTTP readiness, and refuses to report success if health checks fail. Never expose port 8778 publicly; there is no authentication.


### Fix in 0.1.3
The QTS init script under `/etc/init.d` is **not** the application root. The service now uses `getcfg QnapControlCenter Install_Path -f /etc/config/qpkg.conf`, checks that `disk_inspector/` exists at the discovered root, and writes an actionable error to `/var/run/qnapcontrolcenter-startup.log` if not. To inspect configured path: `getcfg QnapControlCenter Install_Path -f /etc/config/qpkg.conf`.
