## Low-disk-I/O behavior

Monitoring reads /proc and keeps the sample ring buffer in RAM. HTTP access logs are suppressed, avoiding a log write every five seconds from browser polling. The Python service already starts with -B to prevent bytecode cache writes.

Verified QPKG downloads now stage only in a mounted /dev/shm RAM filesystem and refuse the operation if RAM capacity is insufficient. No silent /tmp HDD fallback occurs. QTS installer may still use its own temporary directories and will necessarily write files during an upgrade.

No unauthenticated privileged installation API has been introduced. Remove repeated token entry only after a protected pairing/session design and on-NAS validation. Measure disk IOPS before and after starting the app; QTS diskstats readings are physical counters, not necessarily attributable to a particular process.
