# IMS Desktop

A native Tauri app that wraps the IMS Docker Compose stack: launch →
detects Docker → builds/starts the stack → shows a first-run wizard or the
dashboard → quit stops everything cleanly. See issue #174 for the original
design and #189-195 for how the Linux build was shipped. Windows (#226) and
mobile (#234) targets are in progress as additional bundles from this same
Tauri project — see #225 for why this now lives at the repo root instead of
under `desktop/`.

**Looking for install/usage instructions as an end user?** See
[docs/deployment/desktop-app.md](../docs/deployment/desktop-app.md) instead —
this README is for people working on the app itself.

## Prerequisites (Linux)

Linux is the only platform currently shipping (see issue #195); Windows
prerequisites will land with #226. You need:

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

## Prerequisites (Android)

Android is the mobile target currently shipping (see #234); iOS is
explicitly deferred — it requires a macOS + Xcode build host, which wasn't
available when #234 was done. You need everything above (Rust toolchain,
Node.js) plus:

1. **A JDK Gradle actually supports — not necessarily your system's
   default.** Gradle 8.14.3 (the version this project's Android scaffold
   pins) can't run under a too-new JDK: on a machine whose system JDK was
   25, every build failed immediately with `Unsupported class file major
   version 69` (69 is JDK 25's bytecode version). The fix is a JDK 17 or 21
   LTS installed just for this, independent of whatever the system default
   is — the same reason Android Studio bundles its own JDK rather than
   using the system one. A self-contained download works fine, no root/dnf
   needed:
   ```sh
   curl -sL -o temurin21.tar.gz \
     "https://api.adoptium.net/v3/binary/latest/21/ga/linux/x64/jdk/hotspot/normal/eclipse?project=jdk"
   mkdir -p ~/.jdks && tar xzf temurin21.tar.gz -C ~/.jdks/
   mv ~/.jdks/jdk-21* ~/.jdks/temurin-21
   ```
2. **Android SDK command-line tools.**
   ```sh
   mkdir -p ~/Android/Sdk/cmdline-tools
   curl -sL -o cmdline-tools.zip \
     https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
   unzip -q cmdline-tools.zip -d ~/Android/Sdk/cmdline-tools/
   mv ~/Android/Sdk/cmdline-tools/cmdline-tools ~/Android/Sdk/cmdline-tools/latest
   ```
   Then, with `JAVA_HOME` pointed at the JDK from step 1:
   ```sh
   export PATH="$HOME/Android/Sdk/cmdline-tools/latest/bin:$PATH"
   yes | sdkmanager --licenses
   sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.1.0" "ndk;29.0.14206865"
   ```
3. **Rust Android targets:**
   ```sh
   rustup target add aarch64-linux-android armv7-linux-androideabi \
     i686-linux-android x86_64-linux-android
   ```
4. **Environment variables**, every time you build (not just once):
   ```sh
   export JAVA_HOME=~/.jdks/temurin-21
   export ANDROID_HOME="$HOME/Android/Sdk"
   export NDK_HOME="$ANDROID_HOME/ndk/$(ls -1 $ANDROID_HOME/ndk)"
   ```

`npx tauri android init` (already run once — `src-tauri/gen/android/` is
committed) generates the Android Studio project; `npx tauri android build
--target aarch64` (or `npx tauri android dev`) builds/runs it.

**A config gotcha worth knowing if you ever touch `bundle.resources`:**
`tauri.android.conf.json` overrides the base `tauri.conf.json` via JSON
merge-patch semantics, where an **empty object is a no-op, not a clear** —
`"resources": {}` silently keeps whatever the base config already set;
only `"resources": null` actually blanks it out. This mattered here
because the base `tauri.conf.json` bundles the entire Python backend
(`app/`, `dashboard/`, `docker/`, `deploy/`, `migrations/`, `scripts/`) as
resources so *desktop* can locally `docker compose` it — mobile is a
remote thin client (see #227) and should never carry any of that.
`tauri.android.conf.json` sets `"bundle": {"resources": null}` for exactly
this reason; without the explicit `null`, the mobile APK would silently
ship the whole backend source and deploy configs to every phone install.

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

A revocation certificate for the signing key has been generated (see #221)
and is stored offline, outside the repo and off this machine. If the
private key or its passphrase is ever lost or compromised, that
certificate is what lets us publish a revocation and tell anyone who
trusts the public key above that it's no longer good.
