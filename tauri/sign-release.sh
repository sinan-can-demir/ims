#!/usr/bin/env bash
# Signs a built .rpm/.deb/.AppImage with the IMS Desktop release signing
# key. Run this manually after `npm run tauri build` (and, for the
# AppImage, ./scripts/build-appimage.sh) and before publishing a release --
# there's no CI automation for this on purpose (see #213): the private key
# only ever exists on the maintainer's own machine, never in a CI secret.
#
# The .rpm uses rpm's own embedded-signature format (verified via
# `rpm -K`/`dnf`). The .deb and .AppImage don't have rpm's package-manager
# integration, so both get a detached GPG signature instead -- a
# `<file>.asc` alongside the artifact, verified via `gpg --verify` (see
# #339: this is the same key as the .rpm, just a different signature
# mechanism per format, not a weaker one).
#
# Requires:
#   - rpm-sign installed (`sudo dnf install rpm-sign`) -- .rpm only
#   - the release signing key present in your GPG keyring (see
#     docs/deployment/desktop-app.md for the public key; the private key
#     is generated once locally via `gpg --full-generate-key` and never
#     committed anywhere)
#   - ~/.rpmmacros configured (.rpm only):
#       %_signature gpg
#       %_gpg_name IMS Desktop Release Signing Key
set -euo pipefail

GPG_SIGNING_NAME="IMS Desktop Release Signing Key"

ARTIFACT_PATH="${1:-}"
if [ -z "$ARTIFACT_PATH" ]; then
  echo "Usage: $0 <path-to-rpm|deb|AppImage>" >&2
  echo "e.g.: $0 \"src-tauri/target/release/bundle/rpm/IMS Desktop-0.1.0-1.x86_64.rpm\"" >&2
  exit 1
fi

if [ ! -f "$ARTIFACT_PATH" ]; then
  echo "error: $ARTIFACT_PATH does not exist" >&2
  exit 1
fi

case "$ARTIFACT_PATH" in
  *.rpm)
    echo "Signing $ARTIFACT_PATH ..."
    rpmsign --addsign "$ARTIFACT_PATH"

    echo "Verifying signature..."
    rpm -K "$ARTIFACT_PATH"
    ;;
  *.deb|*.AppImage)
    SIG_PATH="$ARTIFACT_PATH.asc"
    echo "Signing $ARTIFACT_PATH (detached GPG signature) ..."
    gpg --local-user "$GPG_SIGNING_NAME" --detach-sign --armor \
      --output "$SIG_PATH" "$ARTIFACT_PATH"

    echo "Verifying signature..."
    gpg --verify "$SIG_PATH" "$ARTIFACT_PATH"
    echo "==> Wrote $SIG_PATH -- publish it alongside $ARTIFACT_PATH"
    ;;
  *)
    echo "error: unrecognized artifact type for $ARTIFACT_PATH (expected .rpm, .deb, or .AppImage)" >&2
    exit 1
    ;;
esac
