"""Reset clears only RAM diagnostics, with private-LAN same-origin POST guard."""
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from disk_inspector.server import State, handler_factory


def sample(ts):
    return {
        "status": "ok", "timestamp": ts,
        "disks": [{"device": "sda", "write_bytes_delta": 4096}],
        "write_events": [{"pid": 100, "starttime": 1, "name": "writer", "write_bytes": 1024}],
        "process_write_bytes": 1024, "omitted_process_write_bytes": 0,
        "monitor_write_bytes": 0, "sampling_ms": 1,
    }


class ResetEndpointTests(unittest.TestCase):
    def setUp(self):
        self.state = State()
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(self.state))
        thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.base = "http://127.0.0.1:%d" % self.http.server_port

    def post(self, *, origin=None, intent=True, mode="write"):
        headers = {"Content-Type": "application/json",
                   "Origin": origin or self.base}
        if intent:
            headers["X-QCC-" + mode.capitalize() + "-Intent"] = "1"
        request = Request(self.base + "/api/" + mode + "-log/reset", data=b"{}",
                          headers=headers, method="POST")
        try:
            with urlopen(request, timeout=4) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, {}

    def test_reset_clears_ram_window_and_allows_next_sample(self):
        self.state.write_log.record(sample(1000))
        self.assertEqual(self.state.write_log.snapshot()["sample_count"], 1)
        code, body = self.post()
        self.assertEqual(code, 200)
        self.assertTrue(body["reset"])
        report = self.state.write_log.snapshot()
        self.assertEqual(report["sample_count"], 0)
        self.assertEqual(report["disk_write_bytes"], 0)
        self.assertFalse(report["top_processes"])
        self.state.write_log.record(sample(1005))
        self.assertEqual(self.state.write_log.snapshot()["sample_count"], 1)

    def test_cross_origin_and_missing_intent_cannot_reset(self):
        self.state.write_log.record(sample(1000))
        self.assertEqual(self.post(origin="https://evil.example")[0], 403)
        self.assertEqual(self.post(intent=False)[0], 403)
        self.assertEqual(self.state.write_log.snapshot()["sample_count"], 1)


    def test_read_reset_is_independent_from_write_and_requires_guard(self):
        self.state.write_log.record(sample(1000))
        read_sample = dict(sample(1000),
            disks=[{"device": "sda", "read_bytes_delta": 8192, "read_ops_delta": 4}],
            read_events=[{"pid": 100, "starttime": 1, "name": "reader",
                          "read_bytes": 2048}],
            process_read_bytes=2048, omitted_process_read_bytes=0,
            monitor_read_bytes=0)
        self.state.read_log.record(read_sample)
        self.assertEqual(self.post(mode="read", origin="https://evil.example")[0], 403)
        self.assertEqual(self.post(mode="read", intent=False)[0], 403)
        self.assertEqual(self.state.read_log.snapshot()["sample_count"], 1)
        self.assertEqual(self.post(mode="read")[0], 200)
        self.assertEqual(self.state.read_log.snapshot()["sample_count"], 0)
        self.assertEqual(self.state.write_log.snapshot()["sample_count"], 1)
        self.state.read_log.record(read_sample)
        self.assertEqual(self.state.read_log.snapshot()["disk_read_ops"], 4)
        self.assertEqual(self.post(mode="write")[0], 200)
        self.assertEqual(self.state.read_log.snapshot()["sample_count"], 1)

if __name__ == "__main__":
    unittest.main()
