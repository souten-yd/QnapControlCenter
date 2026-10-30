# QTS 5.x / TS-253Be installation and validation

QDK QPKG packaging is staged; production release is blocked until the package is built and tested on a real x86_64 QTS 5.x NAS.

- Install QDK on a trusted build machine and run `sh packaging/build.sh`. Confirm generated QPKG contains Python package, HTML, JS, and service script.
- Test QPKG manual install through App Center; confirm start/stop/restart and boot-after-reboot work.
- Python 3.11 at `/opt/bin/python3.11` is preferred, fallback to installed `python3`. Verify required interpreter on NAS.
- Dashboard is intended on port 8778, accessed from trusted LAN or Tailscale only. No public Internet exposure: HTTP API has no authentication.
- Check `/api/status`, physical disk metrics, process read permissions, mount/device mapping, and update discovery.
- Check uninstall/reinstall and upgrade behavior on a backed-up system. Do not publish binary release until real-device validation, checksum, provenance and rollback instructions are available.

Web release discovery works. The explicit token-protected installation path is experimental and remains unverified on NAS. Do not rely on it for recovery; use QTS App Center manual installation and backups.


## ERR_CONNECTION_FAILED troubleshooting
QTS App Center Open should target `http://NAS-IP:8778/` with `QPKG_WEBUI=/`, `QPKG_WEB_PORT=8778`, `QPKG_WEB_SSL_PORT=-2`.
After installing QPKG v0.1.8-rc10 or later, check service status in App Center; SSH diagnostics:

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

## NAS reboot auto-start check

v0.1.8-rc10 configures QTS-managed auto-start for **fresh installs** using QDK's `SYS_QPKG_SERVICE_ENABLED` hook. Upgrades intentionally preserve an existing `Enable=FALSE` or `Enable=TRUE` choice. An installation that QTS had disabled after earlier startup failure must be explicitly re-enabled once in App Center.

The service waits at most 60 seconds for the installed QPKG volume and Python >=3.9, plus at most 20 seconds for HTTP readiness. `QPKG_TIMEOUT=110,20` allows for this bounded start. No cron, persistent restart loop, server-startup build, or second service manager is introduced.

After the NAS has rebooted, verify these values from SSH:

```sh
/sbin/getcfg QnapControlCenter Enable -f /etc/config/qpkg.conf
/sbin/getcfg QnapControlCenter Install_Path -f /etc/config/qpkg.conf
/sbin/getcfg QnapControlCenter Shell -f /etc/config/qpkg.conf
cat /var/run/qnapcontrolcenter-startup.log
netstat -lnt 2>/dev/null | grep ':8778'
curl --max-time 5 http://127.0.0.1:8778/api/status
ls -l /opt/bin/python3.11 /usr/bin/python3 2>/dev/null
```

Expected: `Enable=TRUE`; Shell registered to QnapControlCenter.sh; port 8778 listening; status API HTTP 200. Dependency-timeout errors indicate delayed/unavailable QPKG volume or Python. `/var/run` logs reset on each boot, so collect them before the next reboot. The service respects disabled state on start but does not block stop.

### iPhone / QNAP icons

The build generates a 180x180 `apple-touch-icon.png` for iPhone Safari **Share → Add to Home Screen**, plus 64x64 enabled and grayscale and 80x80 detail PNGs for QDK App Center icons. Remove and recreate an old iPhone shortcut if the icon remains cached. The QPKG build uses `assets/qcc-icon.svg` as its artwork source and depends on `cairosvg` and `Pillow` only on the build machine, not on QTS. Icon display and reboot behavior remain subject to real-NAS verification.
