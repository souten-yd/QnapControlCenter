# Container Station quiet-logging control (QTS 5.x)

## Scope and observed background

On the user's QTS host, `container-station/script/run-docker.sh` appends `-D`
to both Docker daemons and `etc/supervisord.conf` lacks a loglevel.
This produced `Calling HEAD /_ping` DEBUG and
`Get process info of: lxd` INFO lines around every three seconds.
Before changing settings, the observed 60-second log growth was
docker.log +7,487 B and supervisord.log +1,500 B.
After the manual two-line patch and Container Station restart, the user
verified docker.log, system-docker.log, supervisord.log all had **0 B**
growth in a 60-second sample. Physical disk writes do not necessarily
fall proportionally because other services and ext4 journal still write.

This feature automates **only the proven two setting changes**, especially
after a Container Station upgrade replaces QNAP-supplied package files.
It does not auto-run after installation, at QCC startup, or on a timer.

## Web workflow (no SSH / sudo password / token)

1. Open `http://NAS-LAN-IP:8778/` on a **trusted private LAN or Tailscale**.
2. Open **Container Station省書込**, click **設定状態を確認**.
3. If QNAP's update reset the settings, click **ログ抑制を適用** and confirm.
   QCC first checks exact familiar source snippets and contents, then prepares
   a single-use 60-second nonce bound to the device IP and a SHA-256 fingerprint.
   It backs up **both** originals under the Container shared folder,
   preserves the file mode and uid/gid, applies only two substitutions
   atomically, and verifies the resulting recognized layout.
4. To activate the new settings, schedule container downtime, click the
   separate **Container Stationを再起動** button, confirm **twice**.
   The action invokes only the fixed
   `/etc/init.d/container-station.sh restart` QTS service entrypoint if present.
   If it is unavailable, use the **QTS App Center Web UI** instead.
5. Re-check two running Docker daemon arguments and 60-second log growth.
   Check running containers, networks and health checks. A config-file
   match by itself does not prove that new processes inherited the settings.

An already patched package is a **no-op**; after QNAP resets its files the
button is enabled again. Unsupported QNAP layouts **fail closed**; do not
guess offsets, mutate unknown files or restart to "fix" incompatibility.
The exact backup directory is shown after each successful change.
To roll back, restore the matching two backed-up files through a controlled
QTS maintenance process, then restart Container Station in the Web UI.

## Security model and limits

This user explicitly chooses the same trusted-private-LAN rule as the existing
Web QPKG updater. **This is not QTS administrator authentication.** Anyone on
the permitted LAN who can access the Web API can request this fixed mutation
or a Container Station restart, subject to same-origin requests, explicit
browser confirmation, per-peer rate limiting and single-use short-lived
nonces. Use NAS IP not public DNS, do not forward TCP 8778, and do not put
guest or untrusted clients on the same segment. The transport is plain HTTP,
so on-path attackers on a hostile LAN are still a risk.

Only the fixed script and INI under the installed Container Station QPKG
are writable; the API accepts no arbitrary commands, paths, values, URLs,
uploads or scripts. The QCC service must already run with sufficient filesystem
rights (QTS admin process). It never accepts or stores a password.
Default read-only monitor sampling, update package verification, and
write-report generation remain unchanged. No scheduled config writes,
Docker API changes, log deletion or health-check disabling are introduced.
The backup necessarily writes to NAS disk, only after explicit user action.

The restart action can interrupt **all** containers; it is never silently
triggered after patching. QTS firmware variants may not provide the fixed
init script or it may reject `restart`; the UI reports this. QNAP may replace
the two files on any Container Station update. This is deliberate; always
reassess layout before reapplying, rather than installing persistent QTS hooks.

## Device validation checklist

- Reconfirm `GET /api/runtime` returns the running QCC version and build.
- Verify status reflects before/after settings and recognizes an unsupported
  layout as not applicable.
- Check both Docker cmdlines lack `-D` after restart; check neither daemon
  and no containers are unexpectedly missing.
- Record 60 seconds of growth of docker.log, system-docker.log and
  supervisord.log. Expected idle outcome is close to 0 B.
- Compare two 5-minute physical disk write reports only as observational data,
  not proof of strict causal reduction.
- Test a subsequent Container Station update resets settings and Web button
  re-enables; confirm the backup directory and QTS update/rollback behavior.
- If the QCC service is not privileged, the feature must be disabled with a
  clear error and must **not** prompt for sudo credentials.

## Developer tests / safety

Run `python -m unittest discover -s tests -v`,
`node --check disk_inspector/app.js`, and inspect the exact QPKG payload.
Test same-origin nonce replays, invalid JSON, path-injection requests,
unrecognized config, existing divergent loglevel, idempotency,
rollback on write failure, permission handling and no restart on patch.
