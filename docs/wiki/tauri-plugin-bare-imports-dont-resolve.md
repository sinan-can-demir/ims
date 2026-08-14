# Tauri plugin JS packages need a bundler — this frontend doesn't have one

## Summary

While building mobile's server-URL settings screen (#232), `tauri-plugin-store`
was added the normal way: Rust crate on the backend, `@tauri-apps/plugin-store`
on the frontend, imported with `import { load } from "@tauri-apps/plugin-store"`.
It compiled fine and looked correct. On a real Android device it crashed
immediately on page load.

## Why happened?

`tauri/src/index.html` loads `main.js` directly as a browser-native ES module
(`<script type="module" src="/main.js">`) — there's no Vite/webpack/esbuild
step anywhere in this project's frontend. Bare specifiers like
`"@tauri-apps/plugin-store"` only resolve when something (Node, a bundler, an
import map) rewrites them to an actual path; a real browser/webview has no
idea where `@tauri-apps/plugin-store` lives on disk. `cargo check` and `npm
install` both succeeded because neither one loads or resolves frontend JS —
the failure only exists at runtime, inside the actual webview.

Confirmed empirically on a real Android emulator (`adb logcat`), not guessed
from reading the code:

```
E Tauri/Console: File: http://tauri.localhost/ - Line 0 - Msg: Uncaught
TypeError: Failed to resolve module specifier "@tauri-apps/plugin-store".
Relative references must start with either "/", "./", or "../".
```

`@tauri-apps/plugin-store`'s own shipped module (`dist-js/index.js`) makes
this worse, not better — it imports `@tauri-apps/api/event` and
`@tauri-apps/api/core`, both also bare specifiers, so even vendoring the one
file wouldn't have been enough without pulling in that whole chain too.

## Rule

Before adding any `@tauri-apps/*` package to `tauri/src/` or `tauri/src-mobile/`,
check whether it can be avoided in favor of what the webview already provides
natively (`localStorage`, `fetch`, `window.__TAURI__` when
`withGlobalTauri: true`) or via a raw `window.__TAURI__.core.invoke(...)` call.
If a real npm import is unavoidable, this project needs an actual bundler
first — don't assume `cargo check`/`npm install` passing means the frontend
works.

## Fix

Dropped `tauri-plugin-store` (Rust dependency, npm package, and the
`store:default` capability) entirely. `tauri/src/config.js` and
`tauri/src-mobile/config.js` use plain `window.localStorage` instead — no
import needed, sufficient for persisting one string, and it's what desktop's
`main.js` already relied on implicitly (via `window.__TAURI__`, not an npm
import) before this PR touched it.
