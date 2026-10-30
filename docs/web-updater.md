# Web QPKG updater (LAN, v0.1.14-rc16)

The NAS dashboard supports updating from an **ordinary private LAN connection without any manual token or allowlist setup**. Open `http://NAS-IP:8778/`, select the published GitHub QPKG release and confirm **更新をインストール**. The page handles a one-use in-memory confirmation automatically. No SSH setup, manual token or IP permission configuration is necessary.

**Requirements:** NAS service enabled/running, accessible from a private LAN socket IP, and QTS `qpkg_cli` available to the server. If the updater is not available, its status shows why. New updates may temporarily stop the Web UI; after restart confirm `/api/runtime` matches the released package.

**Security:** No QTS identity check is performed for this LAN workflow. Any LAN user/process able to reach the Web service can request installation of **official current QnapControlCenter releases**. Never expose port 8778 to public/guest networks or port-forward it. The same-origin Origin/Host/custom-header checks and one-use nonce prevent ordinary cross-site/double-submit requests, but do not make LAN clients authenticated administrators.

The backend validates the fixed GitHub repository/release, SHA256SUMS, expected size, allowed HTTPS host and fixed `qpkg_cli -m` argument; no user-supplied command, package URL or file path. SHA256SUMS from the same release is not an independent cryptographic signature. Staging is under RAM-mounted `/dev/shm`. The legacy token-authorized API remains only for older external automation; the LAN page never uses it. Real QTS updater success/recovery after an actual installation must be verified on the NAS.

See [LAN update details](lan-update.md).
