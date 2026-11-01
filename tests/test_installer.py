import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from disk_inspector import installer


def asset_data(tag="v0.1.17-rc19"):
    name = "QnapControlCenter_0.1.17_x86_64.qpkg"
    prefix = "https://github.com/souten-yd/QnapControlCenter/releases/download/" + tag + "/"
    body = b"test QPKG bytes"
    digest = hashlib.sha256(body).hexdigest()
    data = {
        "tag_name": tag, "draft": False,
        "assets": [
            {"name": name, "size": len(body), "browser_download_url": prefix + name, "digest": "sha256:" + digest},
            {"name": "SHA256SUMS", "size": 103, "browser_download_url": prefix + "SHA256SUMS"}
        ]
    }
    return data, (digest + "  " + name + "\n").encode(), body


class InstallerTests(unittest.TestCase):
    def test_reject_invalid_tag(self):
        with self.assertRaises(ValueError):
            installer.release("../../evil")

    def test_reject_untrusted_asset_url(self):
        payload, _, _ = asset_data()
        payload["assets"][0]["browser_download_url"] = "https://evil.example/q.qpkg"
        with patch("disk_inspector.installer._read_url", return_value=json.dumps(payload).encode()):
            with self.assertRaises(ValueError):
                installer.release("v0.1.17-rc19")

    def test_checksum_verified_before_staging(self):
        release, sums, body = asset_data()
        with tempfile.TemporaryDirectory() as directory:
            responses = [json.dumps(release).encode(), sums, body]
            with patch("disk_inspector.installer._read_url", side_effect=responses):
                target = installer.stage_verified("v0.1.17-rc19", directory)
            self.assertEqual(target.read_bytes(), body)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_bad_checksum_does_not_stage(self):
        release, sums, body = asset_data()
        with tempfile.TemporaryDirectory() as directory:
            with patch("disk_inspector.installer._read_url", side_effect=[
                json.dumps(release).encode(), sums, body + b"altered"]):
                with self.assertRaises(ValueError):
                    installer.stage_verified("v0.1.17-rc19", directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_token_rejected_without_file(self):
        with patch.object(installer, "TOKEN_FILE") as path:
            path.read_text.side_effect = OSError()
            self.assertFalse(installer.authenticate("anything"))

    def test_environment_requires_qpkg_not_cli(self):
        with patch("disk_inspector.installer.os.geteuid", return_value=1000):
            self.assertFalse(installer.ready())
            self.assertIn("privileges", installer.unavailable_reason())

    def test_status_detects_abandoned_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(installer, "STATUS_FILE", Path(directory)/"status.json"), \
                 patch.object(installer, "LOCK_FILE", Path(directory)/"lock"):
                installer.write_status("downloading", "active")
                result = installer.status()
                self.assertEqual(result["state"], "error")
                self.assertFalse(result["busy"])

    def test_version_comparison(self):
        self.assertEqual(installer.version("v0.1.17-rc19"), (0, 1, 17))
        with self.assertRaises(ValueError):
            installer.version("v0.1.17;rm -rf")


    def test_start_copies_worker_outside_replaceable_qpkg(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(installer, "RAM_ROOT", directory), \
                 patch.object(installer, "LOG_FILE", root/"update.log"), \
                 patch.object(installer, "STATUS_FILE", root/"status.json"), \
                 patch.object(installer, "LOCK_FILE", root/"update.lock"), \
                 patch("disk_inspector.installer.environment", return_value=root/"QnapControlCenter"), \
                 patch("disk_inspector.installer.getcfg", return_value="0.1.16"), \
                 patch("disk_inspector.installer.subprocess.Popen") as popen:
                result = installer.start("v0.1.17-rc19")
                self.assertEqual(result["state"], "queued")
                args, kwargs = popen.call_args
                self.assertEqual(args[0][1], "-B")
                copied = Path(args[0][2])
                self.assertEqual(copied.name, "worker.py")
                self.assertTrue(copied.is_file())
                self.assertTrue(str(copied).startswith(directory + "/qcc-update-"))
                self.assertEqual(kwargs["cwd"], str(copied.parent))
                self.assertTrue(kwargs["start_new_session"])
                self.assertTrue(kwargs["pass_fds"])
                self.assertEqual(json.loads((root/"status.json").read_text())["state"], "queued")

    def test_wait_requires_qpkg_and_matching_web_version(self):
        import io
        from unittest.mock import Mock
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(return_value=io.BytesIO(
            json.dumps({"running_version": "0.1.17", "pid": 543}).encode()))
        opener.open.return_value.__exit__ = Mock(return_value=False)
        def cfg(name):
            return "0.1.17" if name == "Version" else "TRUE"
        with patch("disk_inspector.installer.getcfg", side_effect=cfg), \
             patch("disk_inspector.installer.urllib.request.build_opener", return_value=opener):
            installer.wait_for_version("v0.1.17-rc19", timeout=1)

if __name__ == "__main__":
    unittest.main()
