# QnapControlCenter

Lightweight diagnostic tools for QNAP QTS 5.x. First module: **QnapDiskInspector**, a read-only HDD I/O monitor for TS-253Be.

## Run locally (Python 3.11+)

```sh
python3 -m unittest discover -s tests -v
python3 -m disk_inspector.server --host 127.0.0.1 --port 8778
```

Open http://127.0.0.1:8778. The QPKG service is configured for trusted LAN/Tailscale access on port 8778; do not expose the unauthenticated API publicly.

See `docs/disk-inspector-design.md`, `docs/installation.md`, and `docs/development-release-process.md`.

**Web updates:** GitHub Release update discovery works; direct QPKG application is deliberately disabled pending QTS upgrade safety validation. **Release status:** source-stage preview only; no device-tested QPKG or production release yet.
