# Web QPKG updater (v0.1.17-rc19; QTS device validation pending)

Open http://NAS-LAN-IP:8778/ on a trusted LAN or Tailscale connection. Select 最新版を確認, then explicitly confirm 更新をインストール. The latest published candidate is selected by version among official stable and RC releases. Only official x86_64 QPKGs with a same-release SHA256SUMS can be installed. Never update automatically.

## Update lifecycle

1. Verify enabled QnapControlCenter QPKG registration, installation directory and administrator privilege.
2. Copy a stand-alone updater into a private /dev/shm/qcc-update-* RAM job directory before stopping the app. A /var/run flock is held through Web restart so another update cannot run concurrently.
3. Download from fixed official GitHub URLs. Check filename, length, SHA256SUMS and GitHub asset digest when present. Stage in RAM only; reject client paths and commands.
4. Explicitly stop the old service then execute the verified QDK shell QPKG, as in QnapSelfCare. Installer exit code 0 or 10 is only a candidate, not proof of success.
5. Verify both QTS registered Version and the restarted HTTP /api/runtime running_version. Only then report success.
6. Track queued/checking/downloading/stopping/installing/verifying/success/error with bounded status and log under /var/run; the UI can show the last 16 KiB after service restart.

A disconnected browser never automatically retries. An interrupted worker reports error rather than falsely reporting success. No cron job, always-running daemon, silent install, deletion or automatic rollback is added. Recovery attempts to restart the registered service only after the installer exits.

## API and troubleshooting

- GET /api/runtime — the running Web build.
- GET /api/update-status — update status, busy state, availability and unsupported reason.
- GET /api/update-log — recent log, only for authorized private-LAN sockets.
- GET /api/write-log — rolling RAM diagnostics.

QTS status: /var/run/qnapcontrolcenter-update-status.json. Log: /var/run/qnapcontrolcenter-update.log. These volatile files may be cleared by a NAS reboot.

**Security:** The LAN workflow does NOT authenticate a QTS administrator. An intentional LAN client can invoke official QPKG installation. Restrict TCP 8778 to trusted devices; never expose it publicly or to guest networks. Same-origin checks and one-use confirmations are not a defense against a malicious LAN client. SHA256SUMS from the same release provides integrity but not an independent publisher signature.

Actual upgrade/restart success remains to be confirmed on the NAS hardware.
