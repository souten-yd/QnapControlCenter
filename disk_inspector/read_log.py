"""Bounded, RAM-only 300-second disk and process READ diagnostics.

Reuses the existing /proc diskstats + /proc/PID/io sampler; no second scan,
storage I/O tracing, or file descriptor crawl. Only optional process identity
hints are read from virtual /proc for a few leading readers every 30 seconds.
"""
from collections import defaultdict, deque
import os
from pathlib import Path
import time

from .write_log import WINDOW_SECONDS, MAX_SAMPLES, MAX_PROCESS_RANKS, PKG_PATTERN

HINT_SECONDS = 30
MAX_PROCESSES_TO_HINT = 6


def inspect_reader_identity(pid, starttime, proc=Path("/proc")):
    base = proc / str(pid)
    try:
        stat = (base / "stat").read_text().rsplit(")", 1)[1].split()
        if int(stat[19]) != starttime:
            return None
    except (OSError, ValueError, IndexError):
        return None
    hints = {"executable": "", "cwd": ""}
    for name, key in (("exe", "executable"), ("cwd", "cwd")):
        try:
            hints[key] = os.readlink(base / name)[:240]
        except OSError:
            pass
    return hints


class RollingReadLog:
    def __init__(self, clock=time.monotonic, proc=Path("/proc"),
                 inspector=inspect_reader_identity):
        self.clock = clock
        self.proc = proc
        self.inspector = inspector
        self.samples = deque(maxlen=MAX_SAMPLES)
        self.candidates = {}
        self.last_probe = None

    def reset(self):
        """Clear only read history; never reset the underlying kernel counters."""
        self.samples.clear()
        self.candidates.clear()
        self.last_probe = None

    def record(self, sample):
        now = self.clock()
        if sample.get("status") != "ok":
            self._expire(now)
            return
        processes = sample.get("read_events", [])[:32]
        row = {
            "monotonic": now,
            "timestamp": sample.get("timestamp"),
            "disks": {d["device"]: {
                "read_bytes": d.get("read_bytes_delta", 0),
                "read_ops": d.get("read_ops_delta", 0)}
                for d in sample.get("disks", [])},
            "processes": [dict(pid=e["pid"], starttime=e["starttime"],
                               name=e["name"], read_bytes=e["read_bytes"])
                          for e in processes],
            "process_read_bytes": sample.get("process_read_bytes", 0),
            "other_process_bytes": sample.get("omitted_process_read_bytes", 0),
            "monitor_read_bytes": sample.get("monitor_read_bytes", 0),
            "sampling_ms": sample.get("sampling_ms", 0),
        }
        self.samples.append(row)
        self._expire(now)
        if self.last_probe is None or now - self.last_probe >= HINT_SECONDS:
            self.last_probe = now
            activity = defaultdict(int)
            for item in self.samples:
                if now - item["monotonic"] > HINT_SECONDS:
                    continue
                for event in item["processes"]:
                    activity[(event["pid"], event["starttime"])] += event["read_bytes"]
            for identity in sorted(activity, key=activity.get, reverse=True)[:MAX_PROCESSES_TO_HINT]:
                try:
                    hint = self.inspector(*identity, proc=self.proc)
                except (OSError, ValueError):
                    hint = None
                if hint is not None:
                    self.candidates[identity] = dict(hint, observed_at=row["timestamp"])

    def _expire(self, now):
        while self.samples and now - self.samples[0]["monotonic"] >= WINDOW_SECONDS:
            self.samples.popleft()
        active = {(event["pid"], event["starttime"])
                  for item in self.samples for event in item["processes"]}
        self.candidates = {k: v for k, v in self.candidates.items() if k in active}

    def snapshot(self):
        self._expire(self.clock())
        disks = defaultdict(lambda: {"read_bytes": 0, "read_ops": 0})
        groups = {}
        process_total = monitor_total = other_total = sampling_sum = 0
        timeline = []
        for row in self.samples:
            interval_bytes = interval_ops = 0
            for device, counters in row["disks"].items():
                disks[device]["read_bytes"] += counters["read_bytes"]
                disks[device]["read_ops"] += counters["read_ops"]
                interval_bytes += counters["read_bytes"]
                interval_ops += counters["read_ops"]
            process_total += row["process_read_bytes"]
            other_total += row["other_process_bytes"]
            monitor_total += row["monitor_read_bytes"]
            sampling_sum += row["sampling_ms"]
            for event in row["processes"]:
                key = (event["pid"], event["starttime"])
                entry = groups.setdefault(key, {
                    "pid": event["pid"], "starttime": event["starttime"],
                    "name": event["name"], "read_bytes": 0})
                entry["read_bytes"] += event["read_bytes"]
            timeline.append({
                "timestamp": row["timestamp"], "disk_read_bytes": interval_bytes,
                "disk_read_ops": interval_ops,
                "process_read_bytes": row["process_read_bytes"],
                "monitor_read_bytes": row["monitor_read_bytes"]})
        top = sorted(groups.values(), key=lambda item: item["read_bytes"], reverse=True)
        for entry in top[:MAX_PROCESS_RANKS]:
            identity = (entry["pid"], entry["starttime"])
            hint = self.candidates.get(identity, {})
            entry["executable"] = hint.get("executable", "")
            entry["cwd"] = hint.get("cwd", "")
            entry["candidate_observed_at"] = hint.get("observed_at")
            entry["package_hint"] = next((
                match.group(1) for path in (entry["executable"], entry["cwd"])
                if (match := PKG_PATTERN.search(path))), "")
        physical = [dict(device=device, **counts) for device, counts in sorted(disks.items())]
        return {
            "window_seconds": WINDOW_SECONDS,
            "sample_count": len(self.samples),
            "window_start": timeline[0]["timestamp"] if timeline else None,
            "window_end": timeline[-1]["timestamp"] if timeline else None,
            "disk_read_bytes": sum(x["read_bytes"] for x in physical),
            "disk_read_ops": sum(x["read_ops"] for x in physical),
            "physical_disks": physical,
            "process_read_bytes": process_total,
            "other_process_bytes": other_total,
            "monitor_read_bytes": monitor_total,
            "collector_wall_ms": round(sampling_sum, 2),
            "top_processes": top[:MAX_PROCESS_RANKS],
            "timeline": timeline,
            "limitations": (
                "Physical disk read sectors/operations count actual block-device "
                "activity, including RAID members; device totals may double-count "
                "logical work. /proc/PID/io read_bytes is process I/O accounting "
                "and cannot be added to disk totals or attributed to exact files. "
                "Page-cache hits may cause no physical read; readahead and kernel "
                "work may not be attributed to the initiating process. Read "
                "operations are not seek counts. Executable and cwd are package "
                "hints, NOT confirmed read targets. Unreadable or short-lived "
                "processes may be missing."
            ),
        }
