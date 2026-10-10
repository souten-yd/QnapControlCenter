import unittest
from unittest.mock import patch
from disk_inspector.update import check_latest

class UpdateTests(unittest.TestCase):
    @patch("disk_inspector.update.urlopen")
    def test_release_filter(self, open_mock):
        import io
        open_mock.return_value.__enter__.return_value = io.BytesIO(b'{"tag_name":"v0.1.0","html_url":"https://github.com/souten-yd/QnapControlCenter/releases/tag/v0.1.0","assets":[{"name":"safe.qpkg","size":5,"browser_download_url":"https://github.com/souten-yd/QnapControlCenter/releases/download/v0.1.0/safe.qpkg"},{"name":"other.qpkg","size":7,"browser_download_url":"https://example.com/evil.qpkg"}]}')
        data = check_latest()
        self.assertFalse(data["install_supported"])
        self.assertEqual([a["name"] for a in data["qpkg"]], ["safe.qpkg"])
