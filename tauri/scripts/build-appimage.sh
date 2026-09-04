#!/usr/bin/env bash
# Builds a working AppImage for IMS Desktop (see issue #212).
#
# `cargo tauri build --bundles appimage` alone produces a broken AppImage:
# linuxdeploy's RUNPATH ($ORIGIN) patching step corrupts every bundled
# library it touches (pushes .init's real code into a non-executable LOAD
# segment -- confirmed via gdb/coredump, see issue #212's full comment
# history). The verified fix is to skip trusting the RUNPATH-patched
# copies entirely and restore pristine stock system libraries in their
# place after linuxdeploy runs, then resquash -- this script wires that
# up so `cargo tauri build` alone (still just rpm/msi/nsis, see
# tauri.conf.json) doesn't need to change.
#
# Deliberately NOT wired into CI (matches sign-release.sh's precedent):
# the fix embeds the *build host's own* system libraries as replacements,
# so a CI runner's library set may not reproduce the same corruption or
# the same fix validity. Local/manual only.
#
# Requires:
#   - `cargo tauri build --bundles appimage` already run once on this
#     machine, or run cleanly by this script (downloads/caches
#     linuxdeploy + linuxdeploy-plugin-appimage into ~/.cache/tauri on
#     first use)
#   - readelf (binutils), and rpm or dpkg (to verify replacement
#     libraries are real installed system files, not arbitrary matches)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAURI_DIR="$(dirname "$SCRIPT_DIR")"
BUNDLE_DIR="$TAURI_DIR/src-tauri/target/release/bundle/appimage"

for tool in readelf python3; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "error: $tool not found on PATH" >&2
    exit 1
  fi
done
if ! command -v rpm >/dev/null 2>&1 && ! command -v dpkg >/dev/null 2>&1; then
  echo "error: neither rpm nor dpkg found -- needed to verify replacement libraries" >&2
  exit 1
fi

echo "==> Building AppDir (NO_STRIP=1, linuxdeploy's strip chokes on .relr.dyn -- see issue #212)"
( cd "$TAURI_DIR" && NO_STRIP=1 npm run tauri build -- --bundles appimage )

APPDIR="$(find "$BUNDLE_DIR" -maxdepth 1 -type d -name '*.AppDir' | head -1)"
if [ -z "$APPDIR" ]; then
  echo "error: no .AppDir found under $BUNDLE_DIR after build" >&2
  exit 1
fi
echo "==> AppDir: $APPDIR"

echo "==> Restoring stock system libraries over linuxdeploy's RUNPATH-patched copies"
python3 "$SCRIPT_DIR/restore_stock_appimage_libs.py" "$APPDIR"

echo "==> Sanity check: fix_appimage_dtinit.py should now find nothing to patch"
if ! python3 "$SCRIPT_DIR/fix_appimage_dtinit.py" "$APPDIR" --dry-run; then
  echo "error: fix_appimage_dtinit.py still found mismatches after restore -- restore was incomplete" >&2
  exit 1
fi

LINUXDEPLOY_APPIMAGE_PLUGIN="$HOME/.cache/tauri/linuxdeploy-plugin-appimage.AppImage"
if [ ! -x "$LINUXDEPLOY_APPIMAGE_PLUGIN" ]; then
  echo "error: $LINUXDEPLOY_APPIMAGE_PLUGIN not found -- run a normal tauri AppImage build once first to cache it" >&2
  exit 1
fi

OUTPUT_DIR="$BUNDLE_DIR"

# `tauri build --bundles appimage` (the step above) already produces its
# own .AppImage as a side effect of running linuxdeploy -- built from the
# AppDir *before* our restore pass, so it's still broken. Remove it before
# resquashing so exactly one .AppImage exists afterward: relying on
# timestamps or "most recent" here previously picked the wrong (stale,
# still-broken) file when both were present.
find "$OUTPUT_DIR" -maxdepth 1 -type f -name '*.AppImage' -delete

echo "==> Resquashing $APPDIR"
( cd "$OUTPUT_DIR" && "$LINUXDEPLOY_APPIMAGE_PLUGIN" --appdir "$APPDIR" )

RESULT_APPIMAGE="$(find "$OUTPUT_DIR" -maxdepth 1 -type f -name '*.AppImage' | head -1)"
if [ -z "$RESULT_APPIMAGE" ]; then
  echo "error: resquash did not produce an .AppImage under $OUTPUT_DIR" >&2
  exit 1
fi
chmod +x "$RESULT_APPIMAGE"
echo "==> Built: $RESULT_APPIMAGE"

echo "==> Launch smoke test (5s)"
"$RESULT_APPIMAGE" &
APP_PID=$!
sleep 5
if ! kill -0 "$APP_PID" 2>/dev/null; then
  echo "error: process exited within 5s -- check for a crash" >&2
  if command -v journalctl >/dev/null 2>&1; then
    journalctl --since "-30 seconds" --no-pager 2>/dev/null | grep -i -E "segfault|desktop\[" || true
  fi
  exit 1
fi
kill "$APP_PID" 2>/dev/null || true
wait "$APP_PID" 2>/dev/null || true

echo "==> Smoke test passed: $RESULT_APPIMAGE launched and stayed up for 5s"
echo "==> This is NOT a full verification -- manually run the AppImage and drive it"
echo "    through Docker builds / container creation / DB startup / first-run wizard"
echo "    at least once before treating this as a shippable artifact."
