"""Rolling 5-minute RAM diagnostics and bounded fd candidate discovery."""
import os
from pathlib import Path
import tempfile
import unittest

from disk_inspector.write_log import (
    RollingWriteLog, MAX_FDS_PER_PROCESS, MAX_SAMPLES,
    inspect_writable_fds,
)


def sample(timestamp, pid=91, start=22, write=1024, device=2048,
           name="writer"):
    return {
        "status": "ok",
        "timestamp": timestamp,
        "disks": [{"device": "sda", "write_bytes_delta": device}],
        "write_events": [{"pid": pid, "starttime": start,
                          "name": name, "write_bytes": write}] if write else [],
        "process_write_bytes": write,
        "omitted_process_write_bytes": 0,
        "monitor_write_bytes": 0,
        "sampling_ms": 2.5,
    }


class RollingWriteLogTests(unittest.TestCase):
    def test_five_minute_expiry_by_monotonic_clock(self):
        now = [0.0]
        calls = []
        def inspect(pid, starttime, proc):
            calls.append((pid, starttime))
            return {"paths": ["/share/data/state.db"], "executable": "",
                    "cwd": "/share", "fd_count_checked": 1}
        log = RollingWriteLog(clock=lambda: now[0], inspector=inspect)
        for i in range(62):
            now[0] = i * 5.0
            log.record(sample(1000 + i * 5))
        result = log.snapshot()
        self.assertEqual(result["window_seconds"], 300)
        self.assertEqual(result["sample_count"], 60)
        self.assertEqual(result["disk_write_bytes"], 60 * 2048)
        self.assertEqual(result["process_write_bytes"], 60 * 1024)
        self.assertEqual(result["monitor_write_bytes"], 0)
        self.assertEqual(result["top_processes"][0]["file_candidates"],
                         ["/share/data/state.db"])
        self.assertLessEqual(len(calls), 11)
        self.assertLessEqual(len(log.samples), MAX_SAMPLES)
        now[0] += 301
        result = log.snapshot()
        self.assertEqual(result["sample_count"], 0)
        self.assertFalse(log.candidates)

    def test_limited_memory_under_fast_sampling(self):
        now = [0.0]
        log = RollingWriteLog(clock=lambda: now[0], inspector=lambda *a, **k: None)
        for i in range(500):
            now[0] = i * 1.0
            log.record(sample(1000 + i, write=256))
        self.assertEqual(log.snapshot()["sample_count"], 300)
        self.assertLessEqual(len(log.samples), MAX_SAMPLES)

    def test_pid_reuse_is_not_coalesced(self):
        now = [0.0]
        log = RollingWriteLog(clock=lambda: now[0], inspector=lambda *a, **k: None)
        log.record(sample(1000, pid=91, start=12, write=128))
        now[0] = 5
        log.record(sample(1005, pid=91, start=19, write=256))
        result = log.snapshot()
        self.assertEqual([x["write_bytes"] for x in result["top_processes"]],
                         [256, 128])
        self.assertEqual(result["other_process_bytes"], 0)

    def test_never_confuses_file_candidate_with_byte_count(self):
        now = [0.0]
        def inspect(*args, **kwargs):
            return {"paths": ["/share/maybe.sqlite"], "executable": "/usr/bin/python",
                    "cwd": "/share/CACHEDEV1_DATA/.qpkg/TestPkg", "fd_count_checked": 3}
        log = RollingWriteLog(clock=lambda: now[0], inspector=inspect)
        log.record(sample(1000, write=100))
        result = log.snapshot()
        row = result["top_processes"][0]
        self.assertEqual(row["write_bytes"], 100)
        self.assertEqual(row["package_hint"], "TestPkg")
        self.assertEqual(row["file_candidates"], ["/share/maybe.sqlite"])
        self.assertNotIn("file_write_bytes", row)
        self.assertIn("NOT confirmed", result["limitations"])

    def test_warmup_and_missing_data_keep_no_history(self):
        log = RollingWriteLog(clock=lambda: 1, inspector=lambda *a, **k: None)
        log.record({"status": "warming_up"})
        log.record({"status": "error"})
        self.assertEqual(log.snapshot()["sample_count"], 0)


class FdInspectionTests(unittest.TestCase):
    def test_only_writable_regular_path_hints_and_pid_start_match(self):
        with tempfile.TemporaryDirectory() as temp:
            proc = Path(temp)
            pidroot = proc / "123"
            (pidroot / "fd").mkdir(parents=True)
            (pidroot / "fdinfo").mkdir()
            fields = ["0"] * 20
            fields[19] = "456"
            (pidroot / "stat").write_text("123 (python worker) S " +
                                           " ".join(fields))
            (pidroot / "fdinfo/3").write_text("pos:\t0\nflags:\t0100002\n")
            (pidroot / "fdinfo/4").write_text("pos:\t0\nflags:\t0100000\n")
            (pidroot / "fdinfo/5").write_text("flags:\t0100001\n")
            os.symlink("/share/data/state.db", pidroot / "fd/3")
            os.symlink("/share/data/read-only.db", pidroot / "fd/4")
            os.symlink("socket:[12345]", pidroot / "fd/5")
            os.symlink("/usr/bin/python3", pidroot / "exe")
            os.symlink("/share/CACHEDEV1_DATA/.qpkg/Example", pidroot / "cwd")
            value = inspect_writable_fds(123, 456, proc=proc)
            self.assertEqual(value["paths"], ["/share/data/state.db"])
            self.assertEqual(value["fd_count_checked"], 3)
            self.assertEqual(value["cwd"], "/share/CACHEDEV1_DATA/.qpkg/Example")
            self.assertIsNone(inspect_writable_fds(123, 789, proc=proc))


if __name__ == "__main__":
    unittest.main()
