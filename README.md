# QnapControlCenter

Lightweight diagnostic tools for QNAP QTS 5.x. First module: **QnapDiskInspector**, a read-only HDD I/O monitor for TS-253Be.

## Run locally (Python 3.11+)

```sh
python3 -m unittest discover -s tests -v
python3 -m disk_inspector.server --host 127.0.0.1 --port 8778
```

Open http://127.0.0.1:8778. The QPKG service is configured for trusted LAN/Tailscale access on port 8778; do not expose the unauthenticated API publicly.

See `docs/disk-inspector-design.md`, `docs/installation.md`, and `docs/development-release-process.md`.

**Web updates:** Explicit token-protected install plus opt-in, source-IP allowlisted LAN install. **Release status:** v0.1.11-rc13 is a CI-built candidate only; no device-tested production QPKG.

New installs request QTS-managed auto-start; upgrades preserve QTS's existing enabled/disabled state. Startup has a bounded wait for late-mounted storage/Python. See [reboot checks](docs/installation.md#nas-reboot-auto-start-check).

The iPhone Home Screen and QTS App Center icons are generated from `assets/qcc-icon.svg` during QPKG build (Python CairoSVG and Pillow).

## LAN Web updates (v0.1.9-rc11 candidate)

The dashboard can update QnapControlCenter **without typing a management token** from an explicitly allowlisted LAN client. For safety, LAN updates are disabled by default, and are not enabled simply because the IP is private. Admin-approved setup is one-time via the NAS's QTS configuration; see [LAN update configuration](docs/lan-update.md). When active, the token field disappears on the authorized client's dashboard and an explicit confirmation is still required.

Existing token-based Web updates are preserved for non-allowlisted clients. LAN updates require a numeric NAS LAN address and same-origin requests. They do not authenticate individual QTS users, so only allow devices you fully trust. No Internet/guest-Wi-Fi access; no automatic installation. Real-device QTS upgrade and rollback remain unverified.

## Rolling 5-minute disk write diagnostics

The **書込診断** tab continuously samples existing disk/procfs counters every 5 seconds and holds only the latest **300 seconds in RAM**. The same existing /proc/PID/io scan feeds process totals, without a duplicate process-wide scan. Every 30 seconds the collector examines write-capable /proc/PID/fdinfo descriptors for at most the top 6 writing processes, checking no more than 48 descriptors per process. This adds no normal filesystem content reads or log writes.

The UI reports disk counters, process counters, approximate QPKG owner hints, executable/current directory, write-capable *open-file candidates*, and its own process physical write_bytes delta. Paths are **not confirmed per-file write events** and cannot support exact per-file byte counts without more invasive tracing. RAID, snapshots, journal, permission restrictions and short-lived descriptors can create unattributed writes. See [RAM write diagnostics](docs/ram-write-diagnostics.md) for limitations, memory bounds and security.

## Diagnosing a missing Write Diagnostics control

A GitHub release notification reports the **latest downloadable release**, not the version currently running on the NAS. In v0.1.11-rc13, the header and update section display the version and build ID of the **running Python server**. A prominent **書込診断を表示（直近5分）** button jumps to the diagnostics panel. The live server reports its identity on read-only `GET /api/runtime`, and the write data comes from `GET /api/write-log`.

The QPKG build stamps its source version/commit into `disk_inspector/build_info.json`; CI extracts the actual final QPKG and checks that it contains the HTML button, JavaScript handler, server endpoints and writer collector. This catches package-vs-source drift. Static HTML and JS remain loaded in memory at server startup to avoid repeated disk reads. When a QTS upgrade leaves an old Python PID running, the new QPKG start script will identify the mismatch and stop only its verified own PID, before relaunching; this behavior still needs real-NAS confirmation.

If you still see only the old menu (概要/ディスク/プロセス/更新), the old server is serving the page. In QTS App Center stop and start QnapControlCenter once; then force-reload Safari/Chrome, and inspect `http://NAS-IP:8778/api/runtime` and `http://NAS-IP:8778/api/write-log`. A 404 on the runtime endpoint or a missing diagnostics link usually indicates stale code. Use the App Center manual QPKG installer if the older package remains. Do not kill an arbitrary python PID or expose port 8778 publicly.

## QTS stale/orphan server recovery — 0.1.12-rc14

A real NAS report showed PID file 12734 while disk_inspector.server PID 12825 retained port 8778. The previous stop script trusted only the PID file and the start script incorrectly accepted HTTP 200 from that older listener. The service now enumerates /proc **only at stop/start**, validates both exact startup arguments and the configured QPKG installation working directory, and sends SIGTERM only to matching QnapControlCenter server PIDs. It refuses to kill processes with a different cwd/command. It rejects a port occupied by unrelated or persistent processes; no arbitrary kill, SIGKILL, automatic retry loop, port redirect, or runtime disk writes were added. The readiness check requires /api/runtime to report the exact child PID and installed build ID, never merely 200 from /api/status. A stale PID file is reconciled with the real process identity.

If an existing old service remains after upgrading, QTS App Center Stop → Start should recover it. The first upgrade still requires a real NAS check; record `/var/run/qnapcontrolcenter-startup.log` and `/api/runtime` if unsuccessful. Do not expose port 8778 to the Internet.
