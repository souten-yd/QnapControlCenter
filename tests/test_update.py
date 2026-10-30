import io
import unittest
from urllib.error import HTTPError
from unittest.mock import patch
from disk_inspector.update import check_latest, API, PREVIEW_API

class UpdateTests(unittest.TestCase):
    @patch("disk_inspector.update.urlopen")
    def test_release_filter(self, open_mock):
        open_mock.return_value.__enter__.return_value = io.BytesIO(b'{"tag_name":"v0.1.0","html_url":"https://github.com/souten-yd/QnapControlCenter/releases/tag/v0.1.0","assets":[{"name":"safe.qpkg","size":5,"browser_download_url":"https://github.com/souten-yd/QnapControlCenter/releases/download/v0.1.0/safe.qpkg"},{"name":"other.qpkg","size":7,"browser_download_url":"https://example.com/evil.qpkg"}]}')
        data = check_latest()
        self.assertTrue(data["install_supported"])
        self.assertEqual([a["name"] for a in data["qpkg"]], ["safe.qpkg"])

    @patch("disk_inspector.update._request")
    def test_preview_fallback(self, req):
        req.side_effect = [HTTPError(API, 404, "Not Found", None, None),
                           [{"draft": True}, {"tag_name": "v0.1.0-rc1", "prerelease": True,
                            "html_url": "https://github.com/souten-yd/QnapControlCenter/releases/tag/v0.1.0-rc1",
                            "assets": []}]]
        data = check_latest()
        self.assertTrue(data["prerelease"])
        self.assertEqual(data["tag"], "v0.1.0-rc1")
        self.assertEqual(req.call_args_list[1].args[0], PREVIEW_API)

    @patch("disk_inspector.update._request")
    def test_no_preview(self, req):
        req.side_effect = [HTTPError(API, 404, "Not Found", None, None), []]
        self.assertIsNone(check_latest()["tag"])
