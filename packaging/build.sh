#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
command -v qbuild >/dev/null 2>&1 || { echo "QDK qbuild is required" >&2; exit 1; }
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$ROOT/packaging/." "$STAGE/"
mkdir -p "$STAGE/shared/disk_inspector" "$STAGE/x86_64"
chmod 755 "$STAGE/shared/QnapControlCenter.sh"
cp "$ROOT"/disk_inspector/*.py "$ROOT"/disk_inspector/*.js "$ROOT"/disk_inspector/*.html "$ROOT"/disk_inspector/*.css "$ROOT"/disk_inspector/*.png "$STAGE/shared/disk_inspector/"
# QDK supports --build-arch x86_64 and requires package_routines.
(cd "$STAGE" && qbuild --build-arch x86_64 --build-dir "$ROOT/dist")
test -n "$(find "$ROOT/dist" -maxdepth 1 -name '*.qpkg' -print -quit)"
echo "QPKG created in dist; device validation required before release"
