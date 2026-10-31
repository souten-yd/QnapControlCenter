import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from disk_inspector import container_lowio
from disk_inspector.server import State, handler_factory

DOCKER = ('#!/bin/sh\nDOCKER_OPTS="initial"\n'
          '# Debugger mode for DQV and YT\n'
          'DOCKER_OPTS="$DOCKER_OPTS -D"\n'
          'exec dockerd $DOCKER_OPTS\n')
SUPERVISOR = ('[supervisord]\n'
              'logfile=/var/log/container-station/supervisord.log\n'
              'logfile_maxbytes=1MB\n'
              'pidfile=/var/run/container-station/supervisord.pid\n\n'
              '[program:docker]\nstdout_logfile=/var/log/container-station/docker.log\n')


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        volume = Path(self.tmp.name)
        self.root = volume / ".qpkg" / "container-station"
        (self.root / "script").mkdir(parents=True)
        (self.root / "etc").mkdir()
        self.docker = self.root / "script" / "run-docker.sh"
        self.supervisor = self.root / "etc" / "supervisord.conf"
        self.docker.write_text(DOCKER)
        self.supervisor.write_text(SUPERVISOR)
        self.docker.chmod(0o755)
        self.backup = volume / "Container"
        self.backup.mkdir()

    def test_fixed_snippet_patch_and_idempotent(self):
        self.assertIn('# DOCKER_OPTS="$DOCKER_OPTS -D"',
                      container_lowio.patch_docker(DOCKER))
        self.assertEqual(container_lowio.patch_docker(
            container_lowio.patch_docker(DOCKER)), container_lowio.patch_docker(DOCKER))
        patched = container_lowio.patch_supervisor(SUPERVISOR)
        self.assertIn("loglevel=warn\npidfile=", patched)
        self.assertEqual(container_lowio.patch_supervisor(patched), patched)

    def test_reject_unfamiliar_source_and_duplicate(self):
        for text in (DOCKER.replace('exec dockerd', 'run dockerd'),
                     DOCKER.replace('DOCKER_OPTS="$DOCKER_OPTS -D"', '--debug'),
                     DOCKER.replace('exec dockerd', 'exec dockerd\nexec dockerd')):
            with self.assertRaises(container_lowio.Incompatible):
                container_lowio.patch_docker(text)
        for text in (SUPERVISOR.replace('[supervisord]', '[other]'),
                     SUPERVISOR.replace('logfile_maxbytes=1MB', 'logfile_maxbytes=2MB'),
                     SUPERVISOR.replace('pidfile=', 'loglevel=debug\npidfile=')):
            with self.assertRaises(container_lowio.Incompatible):
                container_lowio.patch_supervisor(text)

    def test_crlf_supervisor(self):
        source = SUPERVISOR.replace('\n', '\r\n')
        self.assertIn('loglevel=warn\r\n', container_lowio.patch_supervisor(source))

    def test_verified_backup_apply_and_noop(self):
        original_mode = stat.S_IMODE(self.docker.stat().st_mode)
        with patch.object(container_lowio.os, "geteuid", return_value=0):
            before = container_lowio.inspect(root=self.root)
            self.assertEqual(before["state"], "needs_apply")
            result = container_lowio.apply(
                before["fingerprint"], root=self.root, backup_parent=self.backup)
            self.assertFalse(result["restart_performed"])
            backup = Path(result["backup"])
            self.assertEqual((backup / "run-docker.sh").read_text(), DOCKER)
            self.assertEqual((backup / "supervisord.conf").read_text(), SUPERVISOR)
            self.assertEqual(stat.S_IMODE(self.docker.stat().st_mode), original_mode)
            self.assertIn("loglevel=warn", self.supervisor.read_text())
            self.assertIn('# DOCKER_OPTS="$DOCKER_OPTS -D"', self.docker.read_text())
            state = container_lowio.inspect(root=self.root)
            self.assertFalse(state["needs_apply"])
            again = container_lowio.apply(
                state["fingerprint"], root=self.root, backup_parent=self.backup)
            self.assertEqual(again["message"], "Already applied, no changes")
            self.assertEqual(len(list(self.backup.iterdir())), 1)

    def test_fingerprint_and_permissions(self):
        original = self.docker.read_bytes()
        plan = container_lowio.inspect(root=self.root)
        with patch.object(container_lowio.os, "geteuid", return_value=0):
            with self.assertRaises(container_lowio.Incompatible):
                container_lowio.apply("0"*64, root=self.root, backup_parent=self.backup)
        with patch.object(container_lowio.os, "geteuid", return_value=1000):
            with self.assertRaises(PermissionError):
                container_lowio.apply(
                    plan["fingerprint"], root=self.root, backup_parent=self.backup)
        self.assertEqual(self.docker.read_bytes(), original)

    def test_second_write_failure_restores_first(self):
        state = container_lowio.inspect(root=self.root)
        write = container_lowio.atomic_write
        attempts = []
        def unreliable(path, data, info):
            attempts.append(path)
            if len(attempts) == 2:
                raise OSError("failure during second write")
            return write(path, data, info)
        with patch.object(container_lowio.os, "geteuid", return_value=0), \
             patch.object(container_lowio, "atomic_write", side_effect=unreliable):
            with self.assertRaises(OSError):
                container_lowio.apply(
                    state["fingerprint"], root=self.root, backup_parent=self.backup)
        self.assertEqual(self.docker.read_text(), DOCKER)
        self.assertEqual(self.supervisor.read_text(), SUPERVISOR)

    def test_symlink_is_rejected_without_mutation(self):
        self.docker.unlink()
        self.docker.symlink_to(self.supervisor)
        state = container_lowio.inspect(root=self.root)
        self.assertEqual(state["state"], "unsupported")

    def test_runtime_gets_process_availability_without_commands(self):
        state = container_lowio.inspect(root=self.root)
        self.assertEqual(state["state"], "needs_apply")


class WebLowioTests(unittest.TestCase):
    def setUp(self):
        self.state = State()
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(self.state))
        t = threading.Thread(target=self.http.serve_forever, daemon=True)
        t.start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.base = "http://127.0.0.1:%d" % self.http.server_port

    def post(self, path, body, origin=None, intent=True):
        headers = {"Origin": self.base if origin is None else origin,
                   "Content-Type": "application/json"}
        if intent:
            headers["X-QCC-Lowio-Intent"] = "1"
        req = Request(self.base + path, data=json.dumps(body).encode(),
                      headers=headers, method="POST")
        try:
            with urlopen(req, timeout=4) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, {}

    def test_prepare_apply_no_token_one_shot(self):
        plan = {"state": "needs_apply", "needs_apply": True, "writable": True,
                "fingerprint": "a" * 64, "changes": ["run-docker.sh"]}
        with patch("disk_inspector.server.container_lowio.inspect", return_value=plan), \
             patch("disk_inspector.server.container_lowio.apply",
                   return_value={"state": "applied"}) as apply:
            code, prepared = self.post("/api/container-lowio/prepare", {})
            self.assertEqual(code, 200)
            body = {"fingerprint": prepared["fingerprint"], "nonce": prepared["nonce"]}
            code, _ = self.post("/api/container-lowio/apply", body)
            self.assertEqual(code, 200)
            code, _ = self.post("/api/container-lowio/apply", body)
            self.assertEqual(code, 403)
            apply.assert_called_once_with("a"*64)

    def test_cross_origin_and_unknown_body_rejected(self):
        with patch("disk_inspector.server.container_lowio.inspect") as inspect:
            code, _ = self.post("/api/container-lowio/prepare", {},
                                origin="https://evil.example")
            self.assertEqual(code, 403)
            code, _ = self.post("/api/container-lowio/prepare", {}, intent=False)
            self.assertEqual(code, 403)
            code, _ = self.post("/api/container-lowio/prepare", {"path": "/etc/passwd"})
            self.assertEqual(code, 400)
            inspect.assert_not_called()

    def test_restart_confirmation_nonce_not_implicitly_applied(self):
        plan = {"state": "applied", "needs_apply": False,
                "restart_available": True}
        with patch("disk_inspector.server.container_lowio.inspect", return_value=plan), \
             patch("disk_inspector.server.container_lowio.request_restart",
                   return_value={"state": "running"}) as restart:
            code, prepared = self.post("/api/container-lowio/prepare-restart", {})
            self.assertEqual(code, 200)
            code, _ = self.post("/api/container-lowio/restart",
                                {"nonce": prepared["nonce"]})
            self.assertEqual(code, 202)
            code, _ = self.post("/api/container-lowio/restart",
                                {"nonce": prepared["nonce"]})
            self.assertEqual(code, 403)
            restart.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
