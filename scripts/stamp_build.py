"""Stamp QPKG metadata at build time; never read Git or execute tools on NAS."""
import argparse
import json
import re
from pathlib import Path

VERSION = re.compile(r'^QPKG_VER="([0-9]+[.][0-9]+[.][0-9]+)"$', re.M)
COMMIT = re.compile(r"^[a-fA-F0-9]{40}$")

def build_info(config, commit=""):
    match = VERSION.search(Path(config).read_text(encoding="utf-8"))
    if not match:
        raise ValueError("QPKG_VER is missing or invalid")
    sha = commit.strip() if COMMIT.fullmatch(commit.strip()) else "local"
    version = match.group(1)
    return {
        "version": version,
        "commit": sha,
        "build_id": version + "+" + (sha[:12] if sha != "local" else "local"),
        "features": ["write_diagnostics", "lan_updater"],
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit", default="")
    args = parser.parse_args()
    info = build_info(args.config, args.commit)
    args.output.write_text(json.dumps(info, sort_keys=True, separators=(",", ":")) + "\n",
                           encoding="utf-8")

if __name__ == "__main__":
    main()
