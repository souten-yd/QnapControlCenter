# Web QPKG updater (v0.1.5-rc6 experimental)

The Web dashboard exposes **更新をインストール** for QTS 5.x test devices. After a one-time manual update to this version, future upgrades can be requested from the Web UI. Actual successful device upgrade is **not yet verified**.

## Initial setup

1. Install v0.1.5-rc6 through QTS App Center once.
2. Ensure `qpkg_cli` exists and the Web UI reports updater available.
3. Over SSH obtain the locally-generated admin token: `cat /var/run/qnapcontrolcenter-update-token` (root/authorized administrator only). The token is generated at service start if absent; it lives in tmpfs and changes after NAS reboot.
4. Paste the token into the Web UI, select latest release, and explicitly confirm. The token is not stored by the browser.
5. Observe update state and reconnect after the QTS service restarts. Check `/var/run/qnapcontrolcenter-update-status.json` if disconnected.

## Security and limitations

The updater accepts only a release tag, validates tag format, fetches GitHub release metadata from the fixed owner/repository, checks the release asset path, requires exactly one QPKG and a SHA256SUMS file, checks package size and SHA256, and invokes `qpkg_cli -m` with a fixed argument pattern. No shell interpolation or caller-provided commands/paths.

**Limitations:** SHA256SUMS from the same GitHub release detects transport corruption but is not an independent signature. The endpoint uses token + same-origin checks over HTTP: restrict port 8778 to a trusted LAN/Tailscale; untrusted Wi-Fi can disclose a token. QTS CLI flags and unsigned-QPKG acceptance can vary by firmware; test on the NAS before treating this as production ready. An independently detached worker is used because QTS may stop the Web process during upgrade. Token and progress state are stored in /var/run (tmpfs). A failed upgrade must be investigated through QTS App Center and device logs. No automatic rollback is claimed.

The first update to v0.1.5 must still be performed manually because older versions do not expose an install API.
