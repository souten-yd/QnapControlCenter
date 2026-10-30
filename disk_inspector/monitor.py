"""Read-only QTS/Linux disk and process I/O sampling. No disk writes."""
import os
import time
from pathlib import Path
PROC = Path("/proc")

def parse_diskstats(content):
    disks = {}
    for line in content.splitlines():
        f = line.split()
        if len(f) < 14:
            continue
        name = f[2]
        # Physical block devices; exclude partitions and virtual devices.
        if not ((name.startswith(("sd", "hd")) and name[-1].isalpha()) or
                (name.startswith("nvme") and "p" not in name)):
            continue
        try:
            disks[name] = dict(reads=int(f[3]), read_sectors=int(f[5]),
                               writes=int(f[7]), write_sectors=int(f[9]), busy_ms=int(f[12]))
        except ValueError:
            continue
    return disks

def get_processes():
    result = {}
    for path in PROC.iterdir():
        if not path.name.isdigit():
            continue
        try:
            stat = (path / "stat").read_text().rsplit(")", 1)[1].split()
            starttime = int(stat[19])
            io = dict(row.split(":", 1) for row in (path / "io").read_text().splitlines() if ":" in row)
            result[(path.name, starttime)] = dict(pid=int(path.name),
                name=(path / "comm").read_text().strip()[:100],
                read=int(io.get("read_bytes", 0)), write=int(io.get("write_bytes", 0)))
        except (OSError, ValueError, IndexError):
            continue
    return result

def difference(old, new, key):
    return max(0, new[key] - old[key])

class Sampler:
    def __init__(self):
        self.previous = None

    def sample(self):
        sample_started = time.monotonic()
        timestamp = time.time()
        now = time.monotonic()
        disks = parse_diskstats((PROC / "diskstats").read_text())
        processes = get_processes()
        if self.previous is None:
            self.previous = (now, disks, processes)
            return dict(status="warming_up", timestamp=timestamp, disks=[], processes=[])
        old_time, old_disks, old_processes = self.previous
        self.previous = (now, disks, processes)
        seconds = max(now - old_time, 0.001)
        disk_rows = []
        for device, counters in disks.items():
            if device not in old_disks:
                continue
            old = old_disks[device]
            disk_rows.append(dict(device=device,
                read_bps=round(difference(old, counters, "read_sectors") * 512 / seconds),
                write_bps=round(difference(old, counters, "write_sectors") * 512 / seconds),
                write_bytes_delta=difference(old, counters, "write_sectors") * 512,
                read_iops=round(difference(old, counters, "reads") / seconds, 2),
                write_iops=round(difference(old, counters, "writes") / seconds, 2),
                busy_pct=round(min(100, difference(old, counters, "busy_ms") / (seconds * 10)), 1)))
        process_rows = []
        write_events = []
        process_written_total = 0
        own_write_bytes = 0
        for key, item in processes.items():
            if key not in old_processes:
                continue
            old = old_processes[key]
            read = max(0, item["read"] - old["read"])
            write = max(0, item["write"] - old["write"])
            if write:
                process_written_total += write
                if item["pid"] == os.getpid():
                    own_write_bytes += write
                write_events.append(dict(pid=item["pid"], starttime=key[1],
                    name=item["name"], write_bytes=write))
            if read or write:
                process_rows.append(dict(pid=item["pid"], name=item["name"],
                    read_bps=round(read / seconds), write_bps=round(write / seconds)))
        process_rows.sort(key=lambda p: p["read_bps"] + p["write_bps"], reverse=True)
        # Reuse the current /proc/PID/io read; no additional process-wide scan.
        write_events.sort(key=lambda p: p["write_bytes"], reverse=True)
        kept = write_events[:32]
        truncated_bytes = process_written_total - sum(p["write_bytes"] for p in kept)
        return dict(status="ok", timestamp=timestamp, interval=round(seconds, 2),
                    disks=disk_rows, processes=process_rows[:30],
                    write_events=kept, process_write_bytes=process_written_total,
                    omitted_process_write_bytes=truncated_bytes,
                    monitor_write_bytes=own_write_bytes,
                    sampling_ms=round((time.monotonic() - sample_started) * 1000, 2),
                    note="Process attribution can miss kernel, cache and inaccessible processes.")
