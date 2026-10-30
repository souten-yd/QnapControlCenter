#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
command -v qbuild >/dev/null 2>&1 || { echo "QDK qbuild is required" >&2; exit 1; }
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$ROOT/packaging/." "$STAGE/"
mkdir -p "$STAGE/shared/disk_inspector" "$STAGE/x86_64" "$STAGE/icons" "$STAGE/generated"
chmod 755 "$STAGE/shared/QnapControlCenter.sh"
cp "$ROOT"/disk_inspector/*.py "$ROOT"/disk_inspector/*.js "$ROOT"/disk_inspector/*.html "$ROOT"/disk_inspector/*.css "$ROOT"/disk_inspector/*.png "$STAGE/shared/disk_inspector/"
# Generate icons once during CI/build; no image processing at QTS startup.
python3 "$ROOT/scripts/render_icons.py" --output "$STAGE/generated"
cp "$STAGE/generated/apple-touch-icon.png" "$STAGE/shared/disk_inspector/apple-touch-icon.png"
# Bundle the exact version and source commit in the package, not just release metadata.
# The NAS reads this tiny JSON once at service startup; no recurring disk scans.
python3 "$ROOT/scripts/stamp_build.py" --config "$ROOT/packaging/qpkg.cfg" \
  --output "$STAGE/shared/disk_inspector/build_info.json" \
  --commit "${GITHUB_SHA:-}"
cp "$STAGE/generated"/QnapControlCenter*.png "$STAGE/icons/"
(cd "$STAGE" && qbuild --build-arch x86_64 --build-dir "$ROOT/dist")
test -n "$(find "$ROOT/dist" -maxdepth 1 -name '*.qpkg' -print -quit)"
echo "QPKG candidate created in dist; real-device boot validation required"
