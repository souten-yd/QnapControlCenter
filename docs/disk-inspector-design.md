# QnapDiskInspector design (QTS 5.x, TS-253Be)

## Goal
Pinpoint noisy disk activity by physical disk, process, and eventually QPKG/application.
This is a *read-only diagnostic monitor*: never stop processes, change disk power management, or execute arbitrary commands.

## Monitoring architecture
- Python stdlib HTTP server and Linux procfs collector; no npm dependency.
- 5-second default sampling, in-memory bounded history, no routine disk logging. Dedicated writer diagnostics use a strictly 300-second window with monotonic expiry.
- Read /proc/diskstats to estimate aggregate physical disk bytes/s, IOPS and busy%.
- Read /proc/PID/io to attribute process read_bytes/write_bytes deltas; key by PID + process starttime to avoid PID reuse.
- Do not claim disk totals equal the sum of process totals: cached writes, journaling, permissions, kernel workers and storage-layer remapping differ.
- UI uses textContent to avoid HTML injection; no POST endpoints in first milestone.
- localhost binding is default. Remote/LAN exposure must be explicitly configured and should be protected by network access controls.
- Diagnostic escalation: correlate high write IOPS/busy% with process ranks, persistent metadata writes, QTS indexers, backup and snapshots. Kernel-only I/O should be labeled unattributed, not assigned to a speculative package.

## Roadmap and acceptance
M0: repo initialization, design and release playbook.
M1: collector + read-only dashboard, unit tests, procfs error tolerance and no writes.
M2: 24h optional buffered history, timeline, per-disk detail, QPKG mapping via verified process ownership heuristics, unattributed I/O.
M3: QPKG build/install scripts verified on QTS 5.x (TS-253Be), restart and stop scripts, service account and minimal permissions, graceful shutdown; optional LAN exposure.
M4: reproducible CI build, SHA256 release assets, on-device smoke test, signed/verified release installation workflow.
All milestones require review of main code, regression tests and absence of unsafe side effects. Never merge a draft or failing build.

## Security and update model
The dashboard may check the latest GitHub Release and display an upstream release link and QPKG asset name.
A web-triggered QPKG installation must NOT be enabled until verified checksum/signature, exact repository and asset allowlisting, downgrade rules, QTS installer behavior, backups, auth/CSRF and rollback/recovery are tested on a supported QTS device.
Until then the UI clearly marks installation unavailable; this avoids misleading claims that opening a URL has updated the NAS.

## Rolling write attribution — v0.1.10-rc12

A single existing procfs sampler produces raw positive process write_bytes deltas by PID plus starttime and physical disk sector delta counters. A separate bounded in-memory log retains up to 300 seconds, and a new read-only /api/write-log endpoint aggregates physical disks (RAID counts may overlap), processes, and activity timeline. The original /api/status history is reduced to 60 entries to minimize RAM overhead.

Once every 30 seconds, up to six leading writers are examined using readlink on /proc/PID/{exe,cwd,fd/*} and virtual /proc/PID/fdinfo flags. These are write-capable open descriptor **candidates**, not verified writes and not per-file bytes. Never open monitored data files. Process expiry is keyed by (PID, starttime), preventing PID reuse confusion. No fanotify, inotify recursive watch, audit daemon, eBPF, strace, external process, disk file log, SQL or server-time build is introduced.

RAM limit: at most 305 samples, at most 32 writers per sample (omitted bytes separately accounted), at most 6 × 8 per FD-probe cycle, and candidates only for active identities in the 300-second history. Actual HTTP JSON is rebuilt in memory. If procfs access is denied, the UI must show an unconfirmed attribution rather than invent a file.
