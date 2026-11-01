"""300-second RAM read totals: physical I/O, process I/O, and bounded hints."""
import unittest

from disk_inspector.read_log import RollingReadLog


def sample(ts, pid=91, start=22, read=1024, disk=4096, ops=3):
    return {
        "status": "ok", "timestamp": ts,
        "disks": [{"device": "sda", "read_bytes_delta": disk, "read_ops_delta": ops}],
        "read_events": ([{"pid": pid, "starttime": start, "name": "reader",
                          "read_bytes": read}] if read else []),
        "process_read_bytes": read, "omitted_process_read_bytes": 0,
        "monitor_read_bytes": 0, "sampling_ms": 1.5
    }


class RollingReadLogTests(unittest.TestCase):
    def test_300_second_window_and_physical_read_operations(self):
        clock = [0.]
        log = RollingReadLog(clock=lambda: clock[0], inspector=lambda *a, **k: None)
        for i in range(62):
            clock[0] = 5. * i
            log.record(sample(1000 + 5*i))
        result = log.snapshot()
        self.assertEqual(result["sample_count"], 60)
        self.assertEqual(result["disk_read_bytes"], 60 * 4096)
        self.assertEqual(result["disk_read_ops"], 60 * 3)
        self.assertEqual(result["process_read_bytes"], 60 * 1024)
        self.assertEqual(result["physical_disks"][0]["read_ops"], 180)
        self.assertEqual(result["timeline"][0]["disk_read_ops"], 3)
        self.assertEqual(len(result["top_processes"]), 1)
        self.assertNotIn("file_candidates", result["top_processes"][0])
        clock[0] += 301
        self.assertEqual(log.snapshot()["sample_count"], 0)

    def test_independent_reset_and_new_measurement(self):
        now = [0]
        log = RollingReadLog(clock=lambda: now[0],
                             inspector=lambda *a, **k: {"executable": "/usr/bin/sh", "cwd": "/share"})
        log.record(sample(1000))
        self.assertEqual(log.snapshot()["sample_count"], 1)
        self.assertTrue(log.candidates)
        log.reset()
        self.assertEqual(log.snapshot()["sample_count"], 0)
        self.assertFalse(log.candidates)
        self.assertIsNone(log.last_probe)
        now[0] = 5
        log.record(sample(1005, read=512))
        self.assertEqual(log.snapshot()["process_read_bytes"], 512)

    def test_pid_reuse_and_process_ranking(self):
        now = [0]
        log = RollingReadLog(clock=lambda: now[0], inspector=lambda *a, **k: None)
        log.record(sample(1000, pid=91, start=12, read=100))
        now[0] = 5
        log.record(sample(1005, pid=91, start=19, read=200))
        out = log.snapshot()
        self.assertEqual([p["read_bytes"] for p in out["top_processes"]], [200, 100])
        self.assertEqual(out["process_read_bytes"], 300)

    def test_missing_samples_not_false_zero_proof(self):
        log = RollingReadLog(clock=lambda: 1, inspector=lambda *a, **k: None)
        log.record({"status": "warming_up"})
        log.record({"status": "error"})
        report = log.snapshot()
        self.assertEqual(report["sample_count"], 0)
        self.assertIn("Page-cache", report["limitations"])

    def test_hints_are_only_executable_and_cwd_no_fd_crawl(self):
        clock = [0]
        log = RollingReadLog(clock=lambda: clock[0],
                             inspector=lambda *a, **k: {
                                 "executable": "/share/.qpkg/Example/bin/python",
                                 "cwd": "/share/.qpkg/Example"})
        log.record(sample(1000))
        p = log.snapshot()["top_processes"][0]
        self.assertEqual(p["package_hint"], "Example")
        self.assertNotIn("file_candidates", p)
        self.assertEqual(p["executable"], "/share/.qpkg/Example/bin/python")
        self.assertNotIn("read_file_bytes", p)


if __name__ == "__main__":
    unittest.main()
