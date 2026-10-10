import unittest
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

if __name__ == "__main__":
    unittest.main()
