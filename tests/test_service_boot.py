"""Hermetic contract checks for QTS boot/enable behavior."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "packaging/shared/QnapControlCenter.sh"
HOOKS = ROOT / "packaging/package_routines"

class ServiceBootTests(unittest.TestCase):
    def test_shell_syntax(self):
        for path in (INIT, HOOKS, ROOT / "packaging/build.sh"):
            subprocess.run(["sh", "-n", str(path)], check=True)

    def test_disabled_start_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            conf = base / "qpkg.conf"
            conf.write_text("[QnapControlCenter]\nEnable = FALSE\nInstall_Path = /missing\n")
            log = base / "startup.log"
            env = dict(os.environ, QCC_QPKG_CONF=str(conf), QCC_LOG=str(log),
                       QCC_PIDFILE=str(base / "service.pid"))
            result = subprocess.run(["sh", str(INIT), "start"], env=env, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing auto-start", log.read_text())
            self.assertFalse((base / "service.pid").exists())

    def test_fresh_install_enable_upgrade_preserves_disabled(self):
        for current_path, expected in (("", "TRUE"), ("/old/qpkg", "FALSE")):
            with self.subTest(current_path=current_path):
                with tempfile.TemporaryDirectory() as temp:
                    getcfg = Path(temp) / "getcfg"
                    getcfg.write_text("#!/bin/sh\nprintf '%s\\n' '" + current_path + "'\n")
                    getcfg.chmod(0o755)
                    command = ("CMD_GETCFG=" + str(getcfg) + "; "
                               "QPKG_NAME=QnapControlCenter; SYS_QPKG_CONFIG_FILE=/test; "
                               "SYS_QPKG_SERVICE_ENABLED=FALSE; log() { :; }; "
                               ". '" + str(HOOKS) + "'; pkg_init; pkg_post_install; "
                               "printf '%s' \"$SYS_QPKG_SERVICE_ENABLED\"")
                    actual = subprocess.check_output(["sh", "-c", command], text=True)
                    self.assertEqual(actual, expected)

if __name__ == "__main__":
    unittest.main()
