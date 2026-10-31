"""Runtime version reporting and shipped UI contract.

The real QPKG artifact is independently inspected in the build workflow.
"""
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from urllib.request import urlopen

from disk_inspector.server import State, handler_factory, read_build_info, runtime_info
from scripts.stamp_build import build_info

ROOT = Path(__file__).resolve().parent.parent


class RuntimeIdentityTests(unittest.TestCase):
    def test_version_matches_manifest(self):
        info = build_info(ROOT / "packaging/qpkg.cfg",
                          "a" * 40)
        self.assertEqual(info["version"], "0.1.16")
        self.assertEqual(info["build_id"], "0.1.16+aaaaaaaaaaaa")
        self.assertIn("write_diagnostics", info["features"])
        self.assertEqual(build_info(ROOT / "packaging/qpkg.cfg")["commit"], "local")

    def test_bad_manifest_fails_closed(self):
        with patch("scripts.stamp_build.Path.read_text", return_value='QPKG_VER="unknown"'):
            with self.assertRaises(ValueError):
                build_info(ROOT / "packaging/qpkg.cfg")

    def test_metadata_missing_is_development_only(self):
        with patch("disk_inspector.server.Path.read_text", side_effect=OSError("missing")):
            info = read_build_info()
        self.assertEqual(info["running_version"] if "running_version" in info
                         else info["version"], "development")

    def test_runtime_endpoint_and_diagnostics_endpoint(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(State()))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = "http://127.0.0.1:%d" % server.server_port
        with urlopen(base + "/api/runtime", timeout=4) as response:
            runtime = json.load(response)
            self.assertEqual(response.headers.get("Cache-Control"),
                             "no-store, max-age=0, must-revalidate")
        self.assertEqual(runtime["features"]["write_diagnostics"], True)
        self.assertIn("running_version", runtime)
        self.assertIn("build_id", runtime)
        self.assertEqual(runtime["diagnostics_endpoint"], "/api/write-log")
        with urlopen(base + "/api/write-log", timeout=4) as response:
            log = json.load(response)
        self.assertEqual(log["window_seconds"], 300)
        self.assertEqual(log["sample_count"], 0)

    def test_html_js_navigation_contract(self):
        html = (ROOT / "disk_inspector/index.html").read_text()
        js = (ROOT / "disk_inspector/app.js").read_text()
        self.assertIn('href="#write-log"', html)
        self.assertIn('id="write-log"', html)
        self.assertIn('id="running-version"', html)
        self.assertIn('id="open-write-log"', html)
        self.assertIn('id="download-write-report"', html)
        self.assertIn('src="/write_report.js"', html)
        self.assertIn('QCCWriteReport.format', js)
        self.assertIn('id="diag-state"', html)
        self.assertIn('id="current-version"', html)
        self.assertIn("'/api/runtime'", js)
        self.assertIn("'/api/write-log'", js)
        self.assertIn("refreshWriteLog();", js)
        self.assertIn("scrollIntoView(", js)

    def test_service_stale_version_guard_present(self):
        launcher = (ROOT / "packaging/shared/QnapControlCenter.sh").read_text()
        self.assertIn("/api/runtime", launcher)
        self.assertIn("Stale PID file", launcher)
        self.assertIn("reconcile_owned", launcher)
        self.assertIn('running.get("pid")', launcher)
        self.assertIn("port_available", launcher)
        self.assertIn("QCC_EXPECTED_INFO", launcher)
        self.assertIn('owned_pid "$recorded"', launcher)
        self.assertIn('owned_pid "$target"', launcher)


if __name__ == "__main__":
    unittest.main()
