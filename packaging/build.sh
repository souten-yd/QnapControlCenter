#!/bin/sh
set -eu
# QDK must be available in the builder. Build outside the NAS.
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
command -v qbuild >/dev/null || { echo "QDK qbuild required" >&2; exit 1; }
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$ROOT/packaging/." "$STAGE/"
mkdir -p "$STAGE/shared/disk_inspector"
cp "$ROOT"/disk_inspector/*.py "$ROOT"/disk_inspector/*.js "$ROOT"/disk_inspector/*.html "$STAGE/shared/disk_inspector/"
(cd "$STAGE" && qbuild)
echo "Inspect QDK build output and validate QPKG on QTS 5.x before publishing"
