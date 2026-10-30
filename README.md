# QnapControlCenter

Lightweight diagnostic tools for QNAP QTS 5.x. First module: **QnapDiskInspector**, a read-only HDD I/O monitor for TS-253Be.

## Run locally (Python 3.11+)

```sh
python3 -m unittest discover -s tests -v
python3 -m disk_inspector.server --host 127.0.0.1 --port 8778
```

Open http://127.0.0.1:8778. The QPKG service is configured for trusted LAN/Tailscale access on port 8778; do not expose the unauthenticated API publicly.

See `docs/disk-inspector-design.md`, `docs/installation.md`, and `docs/development-release-process.md`.

**Web updates:** Explicit token-protected install plus opt-in, source-IP allowlisted LAN install. **Release status:** v0.1.9-rc11 is a CI-built candidate only; no device-tested production QPKG.

New installs request QTS-managed auto-start; upgrades preserve QTS's existing enabled/disabled state. Startup has a bounded wait for late-mounted storage/Python. See [reboot checks](docs/installation.md#nas-reboot-auto-start-check).

The iPhone Home Screen and QTS App Center icons are generated from `assets/qcc-icon.svg` during QPKG build (Python CairoSVG and Pillow).

## LAN Web updates (v0.1.9-rc11 candidate)

The dashboard can update QnapControlCenter **without typing a management token** from an explicitly allowlisted LAN client. For safety, LAN updates are disabled by default, and are not enabled simply because the IP is private. Admin-approved setup is one-time via the NAS's QTS configuration; see [LAN update configuration](docs/lan-update.md). When active, the token field disappears on the authorized client's dashboard and an explicit confirmation is still required.

Existing token-based Web updates are preserved for non-allowlisted clients. LAN updates require a numeric NAS LAN address and same-origin requests. They do not authenticate individual QTS users, so only allow devices you fully trust. No Internet/guest-Wi-Fi access; no automatic installation. Real-device QTS upgrade and rollback remain unverified.
