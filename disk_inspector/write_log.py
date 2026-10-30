"""Bounded, RAM-only 300-second write diagnostics.

The 5s collector already reads /proc/PID/io. This module reuses its deltas,
and only inspects a small number of write-capable open descriptors every 30s.
Descriptors are *candidates*, not evidence of per-file write byte counts.
"""
from collections import defaultdict, deque
from itertools import islice
import os
from pathlib import Path
import re
import time

WINDOW_SECONDS = 300
MAX_SAMPLES = 305
FD_PROBE_SECONDS = 30
MAX_PROCESSES_TO_PROBE = 6
MAX_FDS_PER_PROCESS = 48
MAX_PATHS_PER_PROCESS = 8
MAX_PROCESS_RANKS = 24
PKG_PATTERN = re.compile(r"/\.qpkg/([^/]+)")


def _short(value, limit=240):
    return value[:limit] if isinstance(value, str) else ""


def inspect_writable_fds(pid, starttime, proc=Path("/proc")):
    """Read virtual procfs only. PID reuse protection uses process starttime."""
    base = proc / str(pid)
    try:
        stat = (base / "stat").read_text().rsplit(")", 1)[1].split()
        if int(stat[19]) != starttime:
            return None
    except (OSError, ValueError, IndexError):
        return None
    result = {"paths": [], "executable": "", "cwd": "", "fd_count_checked": 0}
    for name in ("exe", "cwd"):
        try:
            result[{"exe": "executable", "cwd": "cwd"}[name]] = _short(
                os.readlink(base / name))
        except OSError:
            pass
    try:
        # islice caps even a process with thousands of open descriptors.
        with os.scandir(base / "fd") as entries:
            for entry in islice(entries, MAX_FDS_PER_PROCESS):
                if not entry.name.isdigit():
                    continue
                result["fd_count_checked"] += 1
                try:
                    info = (base / "fdinfo" / entry.name).read_text()
                    line = next((x for x in info.splitlines()
                                 if x.startswith("flags:")), "")
                    if not line:
                        continue
                    flags = int(line.split(":", 1)[1].strip(), 8)
                    if getattr(os, "O_PATH", 0) and flags & os.O_PATH:
                        continue
                    if flags & os.O_ACCMODE not in (os.O_WRONLY, os.O_RDWR):
                        continue
                    target = os.readlink(base / "fd" / entry.name)
                    if not target.startswith("/") or target.startswith(
                        ("/dev/", "/proc/", "/sys/")
                    ):
                        continue
                    target = _short(target)
                    if target not in result["paths"]:
                        result["paths"].append(target)
                        if len(result["paths"]) >= MAX_PATHS_PER_PROCESS:
                            break
                except (OSError, ValueError, StopIteration):
                    continue
    except OSError:
        pass
    return result


class RollingWriteLog:
    """Retain only the latest 300 seconds and bounded process/path hints."""
    def __init__(self, clock=time.monotonic, proc=Path("/proc"),
                 inspector=inspect_writable_fds):
        self.clock = clock
        self.proc = proc
        self.inspector = inspector
        self.samples = deque(maxlen=MAX_SAMPLES)
        self.candidates = {}
        self.last_probe = None

    def record(self, sample):
        if sample.get("status") != "ok":
            self._expire(self.clock())
            return
        now = self.clock()
        processes = sample.get("write_events", [])[:32]
        row = {
            "monotonic": now,
            "timestamp": sample.get("timestamp"),
            "disk": {d["device"]: d.get("write_bytes_delta", 0)
                     for d in sample.get("disks", [])},
            "processes": [dict(pid=e["pid"], starttime=e["starttime"],
                               name=e["name"], write_bytes=e["write_bytes"])
                          for e in processes],
            "process_write_bytes": sample.get("process_write_bytes", 0),
            "other_process_bytes": sample.get("omitted_process_write_bytes", 0),
            "monitor_write_bytes": sample.get("monitor_write_bytes", 0),
            "sampling_ms": sample.get("sampling_ms", 0),
        }
        self.samples.append(row)
        self._expire(now)
        if self.last_probe is None or now - self.last_probe >= FD_PROBE_SECONDS:
            self.last_probe = now
            activity = defaultdict(int)
            identity = {}
            for item in self.samples:
                if now - item["monotonic"] > FD_PROBE_SECONDS:
                    continue
                for event in item["processes"]:
                    key = (event["pid"], event["starttime"])
                    activity[key] += event["write_bytes"]
                    identity[key] = event["name"]
            for key in sorted(activity, key=activity.get, reverse=True)[:MAX_PROCESSES_TO_PROBE]:
                try:
                    candidate = self.inspector(*key, proc=self.proc)
                except (OSError, ValueError):
                    candidate = None
                if candidate is not None:
                    candidate["observed_at"] = row["timestamp"]
                    self.candidates[key] = candidate

    def _expire(self, now):
        while self.samples and now - self.samples[0]["monotonic"] >= WINDOW_SECONDS:
            self.samples.popleft()
        active = {(p["pid"], p["starttime"])
                  for item in self.samples for p in item["processes"]}
        self.candidates = {k: v for k, v in self.candidates.items() if k in active}

    def snapshot(self):
        now = self.clock()
        self._expire(now)
        disks = defaultdict(int)
        groups = {}
        process_total = monitor_total = other_total = sampling_sum = 0
        timeline = []
        for row in self.samples:
            physical = sum(row["disk"].values())
            for device, count in row["disk"].items():
                disks[device] += count
            process_total += row["process_write_bytes"]
            other_total += row["other_process_bytes"]
            monitor_total += row["monitor_write_bytes"]
            sampling_sum += row["sampling_ms"]
            for event in row["processes"]:
                key = (event["pid"], event["starttime"])
                entry = groups.setdefault(key, {
                    "pid": event["pid"], "name": event["name"],
                    "starttime": event["starttime"], "write_bytes": 0
                })
                entry["write_bytes"] += event["write_bytes"]
            timeline.append({"timestamp": row["timestamp"],
                "disk_write_bytes": physical,
                "process_write_bytes": row["process_write_bytes"],
                "monitor_write_bytes": row["monitor_write_bytes"]})
        top = sorted(groups.values(), key=lambda x: x["write_bytes"], reverse=True)
        for entry in top[:MAX_PROCESS_RANKS]:
            key = (entry["pid"], entry["starttime"])
            hint = self.candidates.get(key)
            entry["file_candidates"] = hint["paths"] if hint else []
            entry["executable"] = hint["executable"] if hint else ""
            entry["cwd"] = hint["cwd"] if hint else ""
            entry["candidate_observed_at"] = hint["observed_at"] if hint else None
            paths = [entry["executable"], entry["cwd"]] + entry["file_candidates"]
            entry["package_hint"] = next(
                (match.group(1) for p in paths if (match := PKG_PATTERN.search(p))), "")
        return {
            "window_seconds": WINDOW_SECONDS,
            "sample_count": len(self.samples),
            "window_start": timeline[0]["timestamp"] if timeline else None,
            "window_end": timeline[-1]["timestamp"] if timeline else None,
            "disk_write_bytes": sum(disks.values()),
            "physical_disks": [{"device": k, "write_bytes": v}
                               for k, v in sorted(disks.items())],
            "process_write_bytes": process_total,
            "other_process_bytes": other_total,
            "monitor_write_bytes": monitor_total,
            "collector_wall_ms": round(sampling_sum, 2),
            "top_processes": top[:MAX_PROCESS_RANKS],
            "timeline": timeline,
            "limitations": (
                "Physical-device totals are not directly additive with "
                "process write_bytes (RAID, caching, journaling). File names "
                "are observed writable-open descriptor candidates, NOT confirmed "
                "per-file write targets or per-file byte counts. Unreadable "
                "processes and short-lived file descriptors may be missed."
            ),
        }
