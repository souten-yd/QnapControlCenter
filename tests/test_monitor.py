import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch
from disk_inspector.monitor import parse_diskstats, difference, Sampler

class MonitorTests(unittest.TestCase):
    def test_diskstats_filter(self):
        data = "8 0 sda 1 0 2 0 3 0 4 0 0 5 6\n8 1 sda1 2 0 1 0 1 0 1 0 0 5 6\n"
        self.assertEqual(list(parse_diskstats(data)), ["sda"])
        self.assertEqual(parse_diskstats(data)["sda"]["read_sectors"], 2)
    def test_counter_reset(self):
        self.assertEqual(difference({"reads":100},{"reads":1},"reads"),0)
    def test_warmup(self):
        # Sampler is intentionally not invoked against host /proc in unit tests.
        self.assertIsNone(Sampler().previous)

    def test_existing_sampler_yields_read_deltas_and_ops(self):
        from disk_inspector import monitor
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            diskstats = root / "diskstats"
            diskstats.write_text("8 0 sda 10 0 100 0 2 0 3 0 0 4 5\n")
            first = {(100, 50): {"pid": 100, "name": "reader", "read": 1000, "write": 200}}
            second = {(100, 50): {"pid": 100, "name": "reader", "read": 5096, "write": 200}}
            with patch.object(monitor, "PROC", root), \
                 patch.object(monitor, "get_processes", side_effect=[first, second]), \
                 patch.object(monitor.time, "monotonic", side_effect=[0., 0., 5., 5., 5.]), \
                 patch.object(monitor.time, "time", side_effect=[100., 105.]):
                sampler = monitor.Sampler()
                self.assertEqual(sampler.sample()["status"], "warming_up")
                diskstats.write_text("8 0 sda 18 0 116 0 4 0 7 0 0 8 9\n")
                result = sampler.sample()
            self.assertEqual(result["disks"][0]["read_bytes_delta"], 16 * 512)
            self.assertEqual(result["disks"][0]["read_ops_delta"], 8)
            self.assertEqual(result["disks"][0]["write_bytes_delta"], 4 * 512)
            self.assertEqual(result["process_read_bytes"], 4096)
            self.assertEqual(result["process_write_bytes"], 0)
            self.assertEqual(result["read_events"][0]["pid"], 100)
            self.assertEqual(result["omitted_process_read_bytes"], 0)

if __name__ == "__main__":
    unittest.main()
