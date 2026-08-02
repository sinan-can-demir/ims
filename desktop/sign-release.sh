#!/usr/bin/env bash
# Signs a built .rpm with the IMS Desktop release signing key. Run this
# manually after `npm run tauri build` and before publishing a release --
# there's no CI automation for this on purpose (see #213): the private key
# only ever exists on the maintainer's own machine, never in a CI secret.
#
# Requires:
#   - rpm-sign installed (`sudo dnf install rpm-sign`)
#   - the release signing key present in your GPG keyring (see
#     docs/deployment/desktop-app.md for the public key; the private key
#     is generated once locally via `gpg --full-generate-key` and never
#     committed anywhere)
#   - ~/.rpmmacros configured:
#       %_signature gpg
#       %_gpg_name IMS Desktop Release Signing Key
set -euo pipefail

RPM_PATH="${1:-}"
if [ -z "$RPM_PATH" ]; then
  echo "Usage: $0 <path-to-rpm>" >&2
  echo "e.g.: $0 \"src-tauri/target/release/bundle/rpm/IMS Desktop-0.1.0-1.x86_64.rpm\"" >&2
  exit 1
fi

if [ ! -f "$RPM_PATH" ]; then
  echo "error: $RPM_PATH does not exist" >&2
  exit 1
fi

echo "Signing $RPM_PATH ..."
rpmsign --addsign "$RPM_PATH"

echo "Verifying signature..."
rpm -K "$RPM_PATH"
