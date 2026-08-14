# Android release builds silently block all cleartext HTTP

## Summary

While verifying #232 (mobile's server URL is a plain `http://` Tailscale
address by design — the VPN tunnel is the encryption boundary, not TLS on
the HTTP connection itself), a debug APK could reach the backend fine, but
the release APK couldn't reach it at all. No CORS error, no console output,
no crash — the request just never happened.

## Why happened?

Android blocks all cleartext (`http://`) traffic by default for apps
targeting API level 28+, unless the manifest explicitly opts back in via
`android:usesCleartextTraffic="true"`. Tauri's generated
`gen/android/app/src/main/AndroidManifest.xml` already accounts for half of
this — it uses a `${usesCleartextTraffic}` placeholder — but
`gen/android/app/build.gradle.kts` only substitutes `"true"` for the
`debug` build type. The `release` build type (and `defaultConfig`, which it
falls back to) left it at `"false"`.

Confirmed empirically, not assumed: a temporary debug-logging middleware in
`app/main.py` showed the debug build's request landing on the server (and
correctly getting CORS-blocked, since the regex hadn't been updated yet
either) — the release build produced no request at all, with an identical
CSP and identical JS. Verified merged manifests directly
(`gen/android/app/build/intermediates/merged_manifest/universal{Debug,Release}/.../AndroidManifest.xml`)
to confirm the `usesCleartextTraffic` value differed between the two.

This is a completely different mechanism from Tauri's desktop debug-vs-release
origin difference (see the `#192`/`#195` CORS regex comment in
`app/main.py`) — that one's about *which origin the webview presents*; this
one is about whether the OS lets the request leave the device *at all*. Easy
to conflate since both only show up on a real release build.

## Rule

Never assume a debug Android build's network behavior matches release —
Android's cleartext-traffic policy, unlike Tauri's webview origin, differs
by build type in a way that fails completely silently (no console error,
no exception your code can catch). If a mobile feature needs plain HTTP,
verify the actual release APK, not just `--debug`.

## Fix

`gen/android/app/build.gradle.kts`'s `release` build type now sets
`manifestPlaceholders["usesCleartextTraffic"] = "true"` explicitly,
matching the same trade-off `tauri.android.conf.json`'s CSP already makes
(`connect-src http:`) — deliberate for mobile specifically, since its
server address is always a Tailscale host (#227), not exposed to the open
internet.
