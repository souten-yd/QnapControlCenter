# QnapControlCenter

Lightweight diagnostic tools for QNAP QTS 5.x. First module: **QnapDiskInspector**, a read-only HDD I/O monitor for TS-253Be.

## Run locally (Python 3.11+)

```sh
python3 -m unittest discover -s tests -v
python3 -m disk_inspector.server --host 127.0.0.1 --port 8778
```

Open http://127.0.0.1:8778. The QPKG service is configured for trusted LAN/Tailscale access on port 8778; do not expose the unauthenticated API publicly.

See `docs/disk-inspector-design.md`, `docs/installation.md`, and `docs/development-release-process.md`.

**Web updates:** Version lookup works, but the token-protected QTS installer path remains experimental and is not NAS-validated. **Release status:** v0.1.8-rc10 is a CI-built candidate only; no device-tested production QPKG.

New installs request QTS-managed auto-start; upgrades preserve QTS's existing enabled/disabled state. Startup has a bounded wait for late-mounted storage/Python. See [reboot checks](docs/installation.md#nas-reboot-auto-start-check).

The iPhone Home Screen and QTS App Center icons are generated from `assets/qcc-icon.svg` during QPKG build (Python CairoSVG and Pillow).
