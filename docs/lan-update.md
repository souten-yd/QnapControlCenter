# LAN Web updates — no setup or admin token (v0.1.14-rc16)

From this version, open **http://NAS-LAN-IP:8778/** on a trusted private network and use **最新版を確認 → 更新をインストール → 確認**. No `LAN_Update_Enabled`, `LAN_Update_Clients`, SSH token reading, token entry, subnet allowlist or QTS login is required. The former allowlist keys are ignored, not silently enforced.

The Web UI automatically executes a two-step, short-lived confirmation in the background. This is **not** a token the user must type or configure; it prevents cross-site requests and double submission. The user sees only the confirmation dialog.

## Allowed connections

- Actual TCP socket peer and destination must be local/private. RFC1918 addresses (10/8, 172.16/12, 192.168/16), Tailscale/CGNAT 100.64/10, IPv6 unique-local fc00::/7, and NAS loopback pairs are recognized. A public or unrelated remote peer is refused.
- Access the NAS via its **numeric IP:8778**, not an arbitrary hostname or public proxy. Host must equal the actual destination address and port.
- Update POSTs require the same page's Origin, browser same-origin Fetch Metadata (if present), an explicit JSON request, and the app's custom intent header. Forwarded-IP headers are never trusted.
- One-use, 60-second in-memory confirmation is bound to the source address and exact release. Five preparation attempts per client per 10 minutes, 20 total. No arbitrary POST command/path/URL.
- Only the official **souten-yd/QnapControlCenter** GitHub release selected by the server can be installed. Size, filename, release and SHA-256 checks still run. The fixed `qpkg_cli -m <verified-package>` is the only install action. The package is staged in /dev/shm.

## Security and device limitations

**This is NOT QTS administrator authentication.** Any person or software with LAN access to the service can intentionally submit a valid same-origin update using the public Web UI/API. This trades administrator-level approval for local-network convenience. Keep TCP 8778 restricted to a trusted network; disable router port forwarding and guest/Internet access. A network attacker on unencrypted HTTP could be able to interact with the service.

GitHub release SHA256SUMS is downloaded from the same GitHub release as the QPKG. It checks integrity against that source but is **not an independent cryptographic signature**. QTS `qpkg_cli` must exist and the service must have sufficient QTS permissions. Normal QTS upgrades, update worker lifecycle and rollback still need confirmation on the user's NAS; a CI-built QPKG does not prove QTS device upgrade.

The previous explicit-admin-token API path remains for compatibility with older automation, but the LAN Web UI never asks for or requires it. The local update availability check now requires only `qpkg_cli`, not token-file presence. No persistent write log, per-request filesystem scanning, restart scheduler or additional daemon is introduced.

### Troubleshooting

- `GET /api/runtime`: verify running version and build ID. The GitHub latest version displayed on the page is not the NAS installed version.
- `GET /api/update-status`: `lan_available=true` on an accepted LAN connection; `available=true` when `qpkg_cli` is usable.
- `GET /api/write-log`: rolling RAM diagnostics remain read-only and unchanged.
- To check an update failure, inspect Web status and `/var/run/qnapcontrolcenter-update-status.json`. No external URL or arbitrary QPKG upload is accepted.
