"""GitHub release update discovery. Never execute arbitrary downloaded content."""
import json
from urllib.request import Request, urlopen

API = "https://api.github.com/repos/souten-yd/QnapControlCenter/releases/latest"

def check_latest():
    req = Request(API, headers={"Accept":"application/vnd.github+json",
                                 "User-Agent":"QnapControlCenter-DiskInspector"})
    with urlopen(req, timeout=8) as response:
        release = json.load(response)
    assets = [dict(name=a["name"], size=a["size"], url=a["browser_download_url"])
              for a in release.get("assets", [])
              if a["name"].lower().endswith(".qpkg") and a["browser_download_url"].startswith(
                  "https://github.com/souten-yd/QnapControlCenter/releases/download/")]
    return dict(tag=release["tag_name"], release_url=release["html_url"],
                qpkg=assets, install_supported=False,
                message="Installation is not enabled until QTS QPKG upgrade behavior and artifact verification are validated.")
