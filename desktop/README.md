# IMS Desktop

Tauri shell that will eventually wrap the IMS Docker Compose stack in a native
window (see issue #174). This is the bare scaffold from issue #190 — no
Docker lifecycle logic, no wizard UI, no calls into the API yet. It just
proves the toolchain: `cargo tauri dev` opens a native window loading a
static placeholder page.

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
