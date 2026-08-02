# IMS Desktop

A native Tauri app (Linux only, v1) that wraps the IMS Docker Compose stack:
launch → detects Docker → builds/starts the stack → shows a first-run wizard
or the dashboard → quit stops everything cleanly. See issue #174 for the
original design and #189-195 for how it was built out.

**Looking for install/usage instructions as an end user?** See
[docs/deployment/desktop-app.md](../docs/deployment/desktop-app.md) instead —
this README is for people working on the app itself.

## Prerequisites (Linux)

Linux is the only platform in scope for v1 (see issue #195). You need:

1. **Rust toolchain** — stable, 1.77.2 or newer. Install via
   [rustup](https://rustup.rs/):
   ```sh
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   ```
2. **Node.js + npm** — any current LTS. Used only to run the Tauri CLI
   (`@tauri-apps/cli`) and drive scaffolding; the shipped app is a native
   Rust binary and does not bundle or require Node at runtime.
3. **System webview + build dependencies.** Tauri renders through the OS's
   native webview (WebKitGTK on Linux) instead of bundling Chromium, so
   these system packages must be present:

   **Fedora:**
   ```sh
   sudo dnf install webkit2gtk4.1-devel openssl-devel curl wget file \
     libappindicator-gtk3-devel librsvg2-devel
   sudo dnf group install "C Development Tools and Libraries"
   ```

   **Debian / Ubuntu:**
   ```sh
   sudo apt install libwebkit2gtk-4.1-dev build-essential curl wget file \
     libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev
   ```

   Other distros: see the
   [official Tauri Linux prerequisites](https://tauri.app/start/prerequisites/#linux).

## Running

```sh
npm install
npm run tauri dev    # opens a native window, live-reloads on file changes
npm run tauri build   # produces a release bundle under src-tauri/target/release/bundle
```

## Signing a release

Every published `.rpm` should be signed before it's distributed (see #213).
This is a **manual, local-only step** — the private signing key never
leaves the maintainer's machine and is never stored in CI, on purpose.

One-time setup:

```sh
sudo dnf install rpm-sign        # provides `rpmsign`
gpg --full-generate-key          # RSA and RSA, 4096 bits, 2y expiry
```

Then add to `~/.rpmmacros`:

```
%_signature gpg
%_gpg_name IMS Desktop Release Signing Key
```

Per release, after `npm run tauri build`:

```sh
./sign-release.sh "src-tauri/target/release/bundle/rpm/IMS Desktop-<version>-1.x86_64.rpm"
```

This prompts for your GPG passphrase, signs the package, and verifies it.
The public key lives at [`keys/RPM-GPG-KEY-ims-desktop`](keys/RPM-GPG-KEY-ims-desktop)
— safe to commit, that's the whole point of public-key signing. See
[docs/deployment/desktop-app.md](../docs/deployment/desktop-app.md) for how
end users import it to verify a download.
