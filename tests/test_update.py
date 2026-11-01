import io
import unittest
from unittest.mock import patch
from disk_inspector.update import check_latest, PREVIEW_API, release_key


def candidate(tag, prerelease=True, with_checksum=True):
    version = tag[1:].split("-")[0]
    name = "QnapControlCenter_" + version + "_x86_64.qpkg"
    prefix = "https://github.com/souten-yd/QnapControlCenter/releases/download/" + tag + "/"
    assets = [{"name": name, "size": 12345, "browser_download_url": prefix + name}]
    if with_checksum:
        assets.append({"name": "SHA256SUMS", "browser_download_url": prefix + "SHA256SUMS"})
    return {"tag_name": tag, "prerelease": prerelease, "draft": False, "assets": assets}


class UpdateTests(unittest.TestCase):
    @patch("disk_inspector.update._request")
    def test_newer_rc_beats_older_stable(self, request):
        request.return_value = [candidate("v0.1.16-rc18"), candidate("v0.1.15", False)]
        data = check_latest()
        self.assertEqual(data["tag"], "v0.1.16-rc18")
        self.assertTrue(data["install_supported"])
        request.assert_called_once_with(PREVIEW_API)

    @patch("disk_inspector.update._request")
    def test_stable_outranks_same_version_rc(self, request):
        request.return_value = [candidate("v0.1.17-rc19"), candidate("v0.1.17", False)]
        self.assertEqual(check_latest()["tag"], "v0.1.17")

    @patch("disk_inspector.update._request")
    def test_absent_checksum_disables_installation(self, request):
        request.return_value = [candidate("v0.1.17-rc19", with_checksum=False)]
        self.assertFalse(check_latest()["install_supported"])

    @patch("disk_inspector.update._request")
    def test_only_published_valid_tags(self, request):
        draft = candidate("v2.0.0")
        draft["draft"] = True
        request.return_value = [{"tag_name": "bad"}, draft]
        self.assertIsNone(check_latest()["tag"])

    def test_semver_rc_ordering(self):
        self.assertLess(release_key({"tag_name": "v0.1.16-rc9"}),
                        release_key({"tag_name": "v0.1.16-rc10"}))
        self.assertLess(release_key({"tag_name": "v0.1.16-rc10"}),
                        release_key({"tag_name": "v0.1.16"}))


if __name__ == "__main__":
    unittest.main()
