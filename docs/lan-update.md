# LAN Web updater — no extra setup (v0.1.17-rc19)

Use http://NAS-IP:8778/ on trusted private LAN/Tailscale and explicitly confirm the selected official release. This is network trust, NOT QTS user authentication.

## Policy

Both actual socket peer and destination must be loopback or private (RFC1918, 100.64/10, IPv6 ULA). Numeric Host and port must match actual destination. The POST requires same Origin, same-origin Fetch Metadata when present, an explicit JSON content type and the X-QCC-Update-Intent header. A 60-second source-IP/tag-bound nonce is one-use and rate-limited. Forwarded IP headers are ignored. No manual tokens or allowlists are required. Do not port-forward TCP 8778.

## QPKG worker

The validated QDK shell QPKG runs with /bin/sh, not qpkg_cli -m. The updater source is copied to a private /dev/shm directory before replacing its QPKG. The inherited flock and status under /var/run survive a Web service restart. Official asset URL, filename, length and SHA256SUMS are verified before the fixed installer call. The worker verifies QTS registration AND the restarted Web /api/runtime version; installer exit code alone is never treated as success. Logs are accessible via /api/update-log to allowed LAN clients. Lost browser replies are never automatically retried.

For troubleshooting and recovery limitations, see web-updater.md.

## Write diagnostic reset

POST /api/write-log/reset accepts only an empty JSON object and the X-QCC-Write-Intent header with the same LAN + same-origin policy. It clears only rolling RAM samples and FD hints. The /proc sampler continues unchanged. No stored files, virtual machines, containers or QTS settings are affected.
