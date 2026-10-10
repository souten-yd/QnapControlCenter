"""GitHub release discovery only: never apply QPKGs automatically."""
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = "https://api.github.com/repos/souten-yd/QnapControlCenter"
API = BASE + "/releases/latest"
PREVIEW_API = BASE + "/releases?per_page=10"

def _request(url):
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "QnapControlCenter-DiskInspector",
    })
    with urlopen(request, timeout=8) as response:
        return json.load(response)

def check_latest():
    # GitHub's /releases/latest excludes prereleases; candidate releases
    # must remain discoverable for test installations.
    try:
        release = _request(API)
    except HTTPError as exc:
        if exc.code != 404:
            raise
        releases = _request(PREVIEW_API)
        release = next((item for item in releases
                        if not item.get("draft")), None)
        if release is None:
            return dict(tag=None, release_url=None, qpkg=[],
                        install_supported=False, message="No published release yet.")

    assets = []
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        url = asset.get("browser_download_url", "")
        if (name.lower().endswith(".qpkg") and
                url.startswith("https://github.com/souten-yd/QnapControlCenter/releases/download/")):
            assets.append(dict(name=name, size=asset.get("size", 0), url=url))
    return dict(tag=release["tag_name"], release_url=release["html_url"],
                prerelease=bool(release.get("prerelease", False)),
                qpkg=assets, install_supported=False,
                message="Web installation is unavailable until QTS upgrade and recovery are device-verified.")
