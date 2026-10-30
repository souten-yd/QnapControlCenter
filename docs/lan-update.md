# Allowlisted LAN Web updating

QnapControlCenter v0.1.9-rc11 has a **disabled-by-default** LAN convenience mode. It removes the need to type the per-install admin token for explicitly approved devices. This does **not** verify QTS administrator identity. Every person or process on an approved source device can potentially request a package upgrade.

## One-time administrator setup

After upgrading the QPKG, connect to the NAS via SSH as an administrator. Find the private IP of the device that you want to authorize (for an iPhone: Settings → Wi-Fi → network information → IP address). Examples below use the client **192.168.68.20** and NAS **192.168.68.57**; replace with actual values.

```sh
/sbin/setcfg QnapControlCenter LAN_Update_Clients '192.168.68.20/32' -f /etc/config/qpkg.conf
/sbin/setcfg QnapControlCenter LAN_Update_Enabled TRUE -f /etc/config/qpkg.conf
/sbin/getcfg QnapControlCenter LAN_Update_Clients -f /etc/config/qpkg.conf
/sbin/getcfg QnapControlCenter LAN_Update_Enabled -f /etc/config/qpkg.conf
```

Open `http://192.168.68.57:8778/` from that approved client and refresh. The token input is hidden when that client is authorized. Choose **最新版を確認**, then **更新をインストール** and approve the confirmation. The server rechecks the QTS config on every update action, so a service restart is not needed for setting changes.

For multiple trusted devices, use a comma-separated list such as `192.168.68.20/32,192.168.68.21/32`; up to 16 entries. As a convenience, `192.168.68.0/24` permits the entire trusted subnet. Only explicit ranges within RFC1918, CGNAT and unique-local IPv6 addressing are accepted. IPv4 networks wider than /24 and IPv6 networks wider than /64 are refused. If iPhone DHCP changes its address, update the allowlist or configure a DHCP reservation for the device.

## Security boundaries

- The app checks the actual TCP source and listener address; proxy-provided IP headers do not establish trust. Host must contain the NAS's numeric LAN address and matching port; Origin, same-origin Fetch Metadata where present, JSON content type and a custom request-intent header must match.
- A preparation request issues a single-use, 60-second confirmation bound to the client IP and release. Rate limiting caps preparation to five per client in ten minutes and 20 total. Cross-device or repeated execution fails.
- Only the official GitHub release chosen by the server may be prepared. Existing SHA256 verification, maximum package size, RAM staging and fixed QTS command arguments remain unchanged.
- **This is network authorization, not user login authentication.** A compromised approved device, malicious local program, or on-path attacker on an unencrypted LAN may still be dangerous. Use only genuinely trusted devices and networks; block guests, Internet port forwarding and untrusted reverse proxies. Prefer HTTPS via a properly authenticated deployment if your LAN is shared.
- QTS `qpkg_cli` upgrade, service restart and rollback have **not** been validated on a physical NAS in this release candidate. Back up first and keep the preceding QPKG for manual recovery.

## Disable immediately

```sh
/sbin/setcfg QnapControlCenter LAN_Update_Enabled FALSE -f /etc/config/qpkg.conf
```

Afterwards, refresh the Web page. The legacy token-protected install endpoint remains available. If QTS updates alter custom `qpkg.conf` fields, repeat the setting check.

Unmerged experimental QTS session PR #8 is **not** used for this feature; enabling LAN mode does not bypass or weaken QTS 2FA because no QTS password is requested at all. It instead delegates update authorization to an explicit administrator-defined trusted IP allowlist.
