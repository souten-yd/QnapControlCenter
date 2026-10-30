## Low-disk-I/O behavior

Monitoring reads /proc and keeps the sample ring buffer in RAM (the normal /api/status buffer is capped at 60 entries; the dedicated write diagnostic has a separate 300-second monotonic ring). HTTP access logs are suppressed, avoiding a log write every five seconds from browser polling. The Python service already starts with -B to prevent bytecode cache writes.

Verified QPKG downloads now stage only in a mounted /dev/shm RAM filesystem and refuse the operation if RAM capacity is insufficient. No silent /tmp HDD fallback occurs. QTS installer may still use its own temporary directories and will necessarily write files during an upgrade.

No unauthenticated privileged installation API has been introduced. Remove repeated token entry only after a protected pairing/session design and on-NAS validation. Measure disk IOPS before and after starting the app; QTS diskstats readings are physical counters, not necessarily attributable to a particular process.

## Five-minute write diagnostics overhead

The baseline process-wide procfs sampling frequency remains 5 seconds, **not two concurrent scanners**. The write history reuses that exact sample and keeps no files or SQLite database. Stored entries are capped to 305 samples, with at most 32 per-sample process contributors, and automatic monotonic-time eviction after 300 seconds. A lightweight virtual-procfs FD probe runs at most every 30 seconds for six currently active writers, examining at most 48 descriptors each and retaining at most eight write-capable path candidates per process. No file content is read, paths are not recursively scanned, and no persistent log is created.

The Web UI polls the in-memory /api/write-log endpoint every 15 seconds, not on every collector tick. The endpoint is read-only. The sampler measures its own write_bytes delta to reveal unexpected self-generated physical I/O; the expected steady-state value is close to zero but QTS/device behavior must be verified. Imports use Python -B under QTS. Kernel-visible procfs reads consume some CPU and memory even if physical disk reads are normally zero.

Per-process write_bytes is not a file accounting API. Writable FD paths are **possible** targets, not proof of which file received the writes; inspect reported candidates and trace at the kernel level only if truly exact file-level attribution is needed. File paths can be sensitive: keep the unauthenticated read-only dashboard on a trusted LAN only.

## Build identity check cost

A small QPKG-embedded version JSON is read **once on server start**. `/api/runtime` is served from in-memory constants. CI inspects the build artifact during packaging; QTS never runs an asset build or package verification when serving the dashboard. If needed after an upgrade, the QTS start command checks the installed build metadata against the local live API before reusing an old service PID.
