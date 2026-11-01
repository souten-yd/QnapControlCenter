"""Discover newest published stable or RC QPKG; never install automatically."""
import json
import re
from urllib.request import Request, urlopen

REPO = "souten-yd/QnapControlCenter"
PREVIEW_API = "https://api.github.com/repos/" + REPO + "/releases?per_page=30"
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-rc(\d+))?$")


def _request(url):
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "QnapControlCenter-DiskInspector",
    })
    with urlopen(request, timeout=12) as response:
        return json.load(response)


def release_key(release):
    match = TAG.fullmatch(str(release.get("tag_name", "")))
    if not match or release.get("draft"):
        return None
    major, minor, patch, rc = match.groups()
    return (int(major), int(minor), int(patch),
            1 if rc is None else 0, int(rc) if rc else 0)


def check_latest():
    # /releases/latest ignores RC releases even when newer than stable.
    # QCC publishes official, tested-in-CI RC candidates to NAS testers.
    releases = _request(PREVIEW_API)
    if not isinstance(releases, list):
        raise ValueError("Unexpected GitHub releases response")
    valid = [x for x in releases if isinstance(x, dict) and release_key(x)]
    if not valid:
        return dict(tag=None, release_url=None, qpkg=[], install_supported=False,
                    message="No published release yet.")
    release = max(valid, key=release_key)
    tag = release["tag_name"]
    match = TAG.fullmatch(tag)
    name = "QnapControlCenter_" + ".".join(match.groups()[:3]) + "_x86_64.qpkg"
    prefix = "https://github.com/" + REPO + "/releases/download/" + tag + "/"
    assets = [dict(name=a["name"], size=a["size"], url=a["browser_download_url"])
              for a in release.get("assets", [])
              if isinstance(a, dict) and a.get("name") == name
              and isinstance(a.get("size"), int) and not isinstance(a.get("size"), bool)
              and 0 < a["size"] <= 128 * 1024 * 1024
              and a.get("browser_download_url") == prefix + name]
    sums = [a for a in release.get("assets", [])
            if isinstance(a, dict) and a.get("name") == "SHA256SUMS"
            and a.get("browser_download_url") == prefix + "SHA256SUMS"]
    return dict(tag=tag, release_url=prefix.rsplit("/download/", 1)[0] + "/tag/" + tag,
                prerelease=bool(release.get("prerelease", False)),
                qpkg=assets, install_supported=len(assets) == 1 and len(sums) == 1,
                message="Only an official SHA-256-verified release can be installed.")
