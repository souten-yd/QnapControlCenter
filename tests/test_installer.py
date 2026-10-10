import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from disk_inspector import installer

class InstallerTests(unittest.TestCase):
    def test_reject_invalid_tag(self):
        with self.assertRaises(ValueError):
            installer.release("../../evil")
    def test_no_cli_no_ready(self):
        with patch("disk_inspector.installer.shutil.which",return_value=None):
            self.assertFalse(installer.ready())
    def test_reject_untrusted_asset_url(self):
        payload={"tag_name":"v0.1.5-rc6","draft":False,"assets":[
            {"name":"QnapControlCenter.qpkg","size":1234,
             "browser_download_url":"https://evil.example/q.qpkg"},
            {"name":"SHA256SUMS","browser_download_url":"https://github.com/souten-yd/QnapControlCenter/releases/download/v0.1.5-rc6/SHA256SUMS"}]}
        with patch("disk_inspector.installer._read_url",return_value=__import__("json").dumps(payload).encode()):
            with self.assertRaises(ValueError):
                installer.release("v0.1.5-rc6")
    def test_token_rejected_without_file(self):
        with patch("disk_inspector.installer.TOKEN_FILE") as path:
            path.read_text.side_effect=OSError()
            self.assertFalse(installer.authenticate("anything"))
