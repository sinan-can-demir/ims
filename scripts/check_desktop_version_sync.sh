#!/usr/bin/env bash
#
# Checks that the desktop app's version number agrees across the 3 files
# that each carry their own copy, with nothing else keeping them in sync
# (#247): tauri/src-tauri/tauri.conf.json (the source of truth -- it's the
# one that directly controls the version number in every built rpm/msi/nsis
# installer), tauri/package.json, and tauri/src-tauri/Cargo.toml.
#
# Run with no arguments to just check the 3 files agree with each other
# (used by `make desktop-version-check` and every run of release.yml). Pass
# an expected version (no "v" prefix, e.g. "0.2.0") to also check the files
# match it -- release.yml does this on a tag push, so a tag can't silently
# drift from what's actually going to be built.
set -euo pipefail

cd "$(dirname "$0")/.."

TAURI_CONF_VERSION=$(python3 -c "import json; print(json.load(open('tauri/src-tauri/tauri.conf.json'))['version'])")
PACKAGE_JSON_VERSION=$(python3 -c "import json; print(json.load(open('tauri/package.json'))['version'])")
CARGO_TOML_VERSION=$(grep -m1 '^version' tauri/src-tauri/Cargo.toml | sed -E 's/version = "(.*)"/\1/')

fail=0
if [ "$PACKAGE_JSON_VERSION" != "$TAURI_CONF_VERSION" ] || [ "$CARGO_TOML_VERSION" != "$TAURI_CONF_VERSION" ]; then
  echo "Desktop version mismatch across files:" >&2
  echo "  tauri/src-tauri/tauri.conf.json: $TAURI_CONF_VERSION  (source of truth)" >&2
  echo "  tauri/package.json:              $PACKAGE_JSON_VERSION" >&2
  echo "  tauri/src-tauri/Cargo.toml:       $CARGO_TOML_VERSION" >&2
  echo "Update package.json and Cargo.toml to match tauri.conf.json." >&2
  fail=1
fi

EXPECTED_VERSION="${1:-}"
if [ -n "$EXPECTED_VERSION" ] && [ "$TAURI_CONF_VERSION" != "$EXPECTED_VERSION" ]; then
  echo "Tag/expected version ($EXPECTED_VERSION) does not match tauri.conf.json ($TAURI_CONF_VERSION)." >&2
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  exit 1
fi

echo "Desktop version in sync: $TAURI_CONF_VERSION"
