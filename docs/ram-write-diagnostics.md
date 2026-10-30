# RAM-only rolling 5-minute disk write log

QnapControlCenter continuously samples the physical disk and per-process write counters from the existing Linux procfs collector. It **does not periodically write a log file** to storage.

## Collection and retention

- Physical disk sector-write deltas and process `/proc/PID/io write_bytes` counters are sampled every **5 seconds** (same collector already serving disk monitor).
- A separate bounded RAM ring is expired by `time.monotonic()` every tick. Entries at least **300 seconds** old disappear automatically, even when sample interval changes.
- No more than **305** interval records (up to 32 top writers per record) are stored. Omitted contributors' bytes remain separately counted. The normal status ring is reduced from 720 to 60 entries.
- Every **30 seconds**, the six most active writers from the last 30 seconds are checked for open write-capable descriptors. At most 48 descriptor metadata entries per process are inspected and at most eight candidate paths retained. `/proc/PID/stat` starttime is checked before inspecting a PID to protect against PID reuse.
- `/proc/PID/exe` and `/proc/PID/cwd` provide optional executable / working-directory hints. `.qpkg/<package>` found in those paths is only a **package hint**, not verified ownership.
- All history, hints and JSON are assembled in **RAM**. There are no routine files, databases, extra processes, scheduler tasks or new kernel tracer dependencies. The Web UI polls the in-memory API every 15 seconds. Python startup uses `-B` to avoid bytecode cache writes.

## What the results do and do not prove

- **Physical disk sectors** show bytes submitted to each physical block device. Summing RAID member drives can double-count the same logical write.
- **Process `write_bytes`** is per-process kernel I/O accounting, not a direct breakdown of physical disk sectors, especially with buffering, journaling, delayed writeback and snapshots.
- **File candidates** represent writable-open descriptors observed at the probe instant. They are **not** confirmed as written during the 5-minute window; no exact per-file byte count can be determined by polling procfs alone. Short-lived file openings can be missed.
- Kernel threads, inaccessible procfs files, cached writeback, and process terminations may appear unattributed. `monitor_write_bytes` lets users check the monitor's own physical-write counter delta. Under normal operation it is expected to be near zero, but this requires NAS observation.

For exact write events and file byte accounting a separately designed privileged trace would be necessary; this implementation deliberately avoids its overhead and security consequences.

## Privacy and safety

The read-only `GET /api/write-log` response may contain real absolute paths under `/share`, so do not expose TCP 8778 on untrusted networks. Monitor HTTP logs stay suppressed. Treat a path as a diagnosis lead, not proof. No process stopping, file deletion, disk scans, or automatic remediation is performed.

## Acceptance

- Five-second samples are collected continuously without browser attendance.
- Oldest samples and hints are evicted when older than 300 seconds, even under high sample frequency.
- 5-minute top writers, cumulative physical disk writes, process totals and candidate paths display in the Japanese UI.
- Server's own disk write counter and sampling wall time are displayed for overhead monitoring.
- Read-only endpoint, no new POST or execution behavior, existing update authentication untouched.
