"""Regression tests for stale QTS PID files and false HTTP readiness.

These tests launch only temporary harmless fake server processes owned by the test.
They never signal arbitrary PIDs or mutate the real NAS.
"""
import json
import os
import shutil
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
SERVICE = ROOT / "packaging/shared/QnapControlCenter.sh"

FAKE_SERVER = '''
import json, os, time
if os.environ.get("QCC_FAKE_LISTEN") == "TRUE":
    from http.server import HTTPServer, BaseHTTPRequestHandler
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/runtime":
                data = {
                    "build_id": os.environ.get("QCC_FAKE_BUILD", "old"),
                    "pid": os.getpid(),
                    "features": {"write_diagnostics": True},
                }
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(200)
                self.end_headers()
        def log_message(self, *args):
            pass
    HTTPServer(("0.0.0.0", 8778), Handler).serve_forever()
else:
    time.sleep(45)
'''

class StaleProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.installed = base / "installed"
        self.foreign = base / "foreign"
        for folder in (self.installed, self.foreign):
            module = folder / "disk_inspector"
            module.mkdir(parents=True)
            (module / "__init__.py").write_text("")
            (module / "server.py").write_text(FAKE_SERVER)
        self.config = base / "qpkg.conf"
        self.config.write_text("[QnapControlCenter]\nEnable = TRUE\n"
                               "Install_Path = " + str(self.installed) + "\n")
        self.pidfile = base / "service.pid"
        self.log = base / "startup.log"
        self.env = dict(os.environ)
        self.env.update(QCC_QPKG_CONF=str(self.config),
                        QCC_PIDFILE=str(self.pidfile),
                        QCC_LOG=str(self.log))
        self.spawned = []
        self.addCleanup(self.cleanup_procs)

    def cleanup_procs(self):
        for process in self.spawned:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)

    def spawn(self, folder, listener=False, build="old"):
        env = dict(self.env, PYTHONPATH=str(folder),
                   QCC_FAKE_LISTEN="TRUE" if listener else "FALSE",
                   QCC_FAKE_BUILD=build)
        proc = subprocess.Popen([
            sys.executable, "-B", "-m", "disk_inspector.server",
            "--host", "0.0.0.0", "--port", "8778",
        ], cwd=folder, env=env, stdout=subprocess.DEVNULL,
           stderr=subprocess.DEVNULL)
        self.spawned.append(proc)
        for _ in range(60):
            if proc.poll() is not None:
                raise AssertionError("fake server exited early")
            try:
                if Path("/proc/%d/cwd" % proc.pid).resolve() == folder:
                    break
            except OSError:
                pass
            time.sleep(0.05)
        else:
            raise AssertionError("fake server did not begin")
        if listener:
            for _ in range(60):
                try:
                    with socket.create_connection(("127.0.0.1", 8778), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                raise AssertionError("fake listener did not bind")
        return proc

    def run_service(self, operation):
        return subprocess.run(["sh", str(SERVICE), operation], env=self.env,
                              capture_output=True, text=True, timeout=25)

    def test_stop_recovers_orphan_while_pidfile_is_stale(self):
        process = self.spawn(self.installed)
        self.pidfile.write_text("12734\n")
        result = self.run_service("stop")
        self.assertEqual(result.returncode, 0, result.stderr + self.log.read_text())
        process.wait(timeout=3)
        self.assertIsNotNone(process.returncode)
        self.assertFalse(self.pidfile.exists())
        self.assertIn("Stale PID file", self.log.read_text())
        self.assertIn("Stopping owned", self.log.read_text())

    def test_stop_recovers_deleted_qpkg_workdir_after_upgrade(self):
        process = self.spawn(self.installed)
        # QDK replaces the previous package directory while the old worker
        # remains alive; Linux procfs then reports "<Install_Path> (deleted)".
        shutil.rmtree(self.installed)
        module = self.installed / "disk_inspector"
        module.mkdir(parents=True)
        (module / "server.py").write_text(FAKE_SERVER)
        self.assertEqual(os.readlink("/proc/%d/cwd" % process.pid),
                         str(self.installed) + " (deleted)")
        self.pidfile.write_text("12734\n")
        result = self.run_service("stop")
        self.assertEqual(result.returncode, 0, result.stderr + self.log.read_text())
        process.wait(timeout=3)
        self.assertIsNotNone(process.returncode)
        self.assertFalse(self.pidfile.exists())
        self.assertIn("Stopping owned QnapControlCenter server", self.log.read_text())

    def test_deleted_other_qpkg_directory_is_not_owned(self):
        process = self.spawn(self.foreign)
        shutil.rmtree(self.foreign)
        self.assertEqual(os.readlink("/proc/%d/cwd" % process.pid),
                         str(self.foreign) + " (deleted)")
        self.pidfile.write_text(str(process.pid) + "\n")
        result = self.run_service("stop")
        self.assertEqual(result.returncode, 0)
        self.assertIsNone(process.poll())
        self.assertNotIn("Stopping owned", self.log.read_text())

    def test_same_directory_wrong_python_command_is_not_owned(self):
        process = subprocess.Popen(
            [sys.executable, "-B", "-c", "import time; time.sleep(45)"],
            cwd=self.installed, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        self.spawned.append(process)
        # Wait for the process to finish startup and take its cwd.
        for _ in range(50):
            try:
                if os.readlink("/proc/%d/cwd" % process.pid) == str(self.installed):
                    break
            except OSError:
                pass
            time.sleep(0.05)
        self.pidfile.write_text(str(process.pid) + "\n")
        result = self.run_service("stop")
        self.assertEqual(result.returncode, 0)
        self.assertIsNone(process.poll())
        self.assertNotIn("Stopping owned", self.log.read_text())

    def test_stop_never_kills_same_module_from_another_install_dir(self):
        process = self.spawn(self.foreign)
        self.pidfile.write_text(str(process.pid) + "\n")
        result = self.run_service("stop")
        self.assertEqual(result.returncode, 0)
        self.assertIsNone(process.poll(), "unrelated process must remain running")
        self.assertNotIn("Stopping owned", self.log.read_text())

    def test_occupied_foreign_port_refuses_false_readiness(self):
        foreign = self.spawn(self.foreign, listener=True)
        self.pidfile.write_text("12734\n")
        result = self.run_service("start")
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(foreign.poll(), "foreign port holder must not be killed")
        self.assertIn("port 8778 is occupied", self.log.read_text())
        self.assertNotIn("Web UI ready", self.log.read_text())

    def test_matching_existing_process_repairs_stale_pidfile(self):
        (self.installed / "disk_inspector/build_info.json").write_text(
            json.dumps({"build_id": "0.1.13+test"}))
        process = self.spawn(self.installed, listener=True, build="0.1.13+test")
        self.pidfile.write_text("12734\n")
        result = self.run_service("start")
        self.assertEqual(result.returncode, 0, self.log.read_text())
        self.assertEqual(self.pidfile.read_text().strip(), str(process.pid))
        self.assertIsNone(process.poll())
        self.assertIn("Reusing verified running build", self.log.read_text())

if __name__ == "__main__":
    unittest.main()
