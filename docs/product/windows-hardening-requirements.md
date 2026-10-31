# Windows Hardening: Requirements and Use Cases (2026-10-30)

## Why this exists

IMS's Windows desktop build exists (Tauri shell + Docker Desktop/WSL2
stack, `msi` and `nsis` bundles) but has only been smoke-tested in CI and
is unsigned. Sinan plans to use IMS as a real solution on Windows, so
"it builds" is no longer the bar. This doc fixes the target before any
code changes: who uses it, what they must be able to do, and what
"hardened" means in testable terms.

`CLAUDE.md` deprioritizes Windows (Linux-only focus). This work was
**explicitly requested** on 2026-10-30, which is the exception that rule
allows. Linux behavior must not regress.

**Status of the findings below:** they come from reading the repo, not
from running IMS on Windows. Anything marked *(unverified)* needs a real
Windows machine. The repo itself disagrees about prior verification:
`tauri/README.md` says the build and per-user install were verified on
real hardware but not the Docker happy path; `ROADMAP.md` says the
verification pass never happened. Treat Windows as unverified until a
checklist in section 7 is run.

## 1. Scope and assumptions

- **In scope:** the Windows desktop app: installer, first launch, daily
  use, upgrade, uninstall, and its local security posture.
- **Deployment assumption:** one non-technical owner on a single Windows
  10/11 PC, running IMS locally. Shared-LAN access is a **future** use
  case (UC-7), not designed here.
- **Out of scope:** Windows containers mode (#226), mobile, macOS, and
  hosted/multi-user cloud deployment.
- **Architecture fact:** there is no bundled backend binary. The app
  drives `deploy/docker-compose.yml` through the `docker` CLI, so Docker
  Desktop + WSL2 is a hard runtime dependency.

## 2. Actors

| Actor | Description |
|---|---|
| Owner | Non-technical, installs and uses the app, has local admin rights |
| Other local user | Another account on the same PC; should not reach the owner's data |
| Network peer | Any device on the same LAN/Wi-Fi |
| Maintainer | Sinan: builds, signs, and ships releases |

## 3. Use cases

| ID | Use case | Main flow | Key failure paths |
|---|---|---|---|
| UC-1 | Install | Download installer, verify, run, launch | SmartScreen warning (unsigned); WebView2 missing on Win10; UAC friction (#268) |
| UC-2 | First launch | App detects Docker, starts stack, shows dashboard | Docker not installed / not running; WSL2 missing; virtualization disabled (#262); port in use |
| UC-3 | Daily use | Open app, use dashboard/API, close | Stack stopped; backend unreachable; console windows flashing |
| UC-4 | Upgrade | Install newer version over old | Data loss; version skew between app and DB migrations; no updater exists |
| UC-5 | Uninstall | Remove app | Docker volume (all inventory data) orphaned or silently deleted |
| UC-6 | Backup/recover | Export or restore data | Data lives only in the Docker volume inside the WSL2 disk image |
| UC-7 | (Future) LAN access | Staff connect from other devices | Needs auth hardening, TLS, firewall rules |

## 4. Requirements

Priority: **M** = must before real use, **S** = should, **C** = could.
"Verify" says how it is proven; *HW* means it needs a real Windows machine.

### Security (SEC)

| ID | Requirement | Pri | UC | Acceptance criterion | Verify |
|---|---|---|---|---|---|
| SEC-1 | Services listen on loopback only by default | M | 2,3 | `5432` and `8000` are published as `127.0.0.1:port`; a peer on the LAN cannot connect | `ss -ltn` / compose config on Linux; LAN probe *HW* |
| SEC-2 | Postgres is not published to the host at all in the desktop stack | M | 2,3 | No host port mapping for the `db` service; API still reaches it over the compose network | compose up + API health |
| SEC-3 | Each install uses a unique, random JWT secret | M | 2,3 | With `JWT_SECRET` unset, the desktop path generates and persists one; the public `insecure-dev-secret-...` fallback is not used (currently in `app/core/auth.py:23` and `app/services/square_service.py:37`) | pytest + launch |
| SEC-4 | Default DB credentials are not the public `postgres:postgres` pair | S | 2 | Generated per install | compose up |
| SEC-5 | CORS allows only the app's real origins; Windows origin is tested | M | 3 | `http://tauri.localhost` is allowed by test and documented; wildcard methods/headers reviewed | pytest; real WebView2 origin *HW* |
| SEC-6 | CSP and Tauri capabilities stay minimal | S | 3 | Capabilities remain `core:default` + `log:default`; CSP change reviewed (consider adding `127.0.0.1`) | config review |
| SEC-7 | Releases are signed and verifiable | M | 1 | Authenticode-signed `msi`/`exe` with timestamp, plus published checksums; end-user verify steps documented | *HW* + cert (blocked on #229) |

### Reliability (REL)

| ID | Requirement | Pri | UC | Acceptance criterion | Verify |
|---|---|---|---|---|---|
| REL-1 | Docker/WSL2 failure classification is unit-tested | S | 2 | Rust tests cover `VirtualizationDisabled`, `Wsl2Missing`, `NotRunning`, `PortConflict` parsing | `cargo test` |
| REL-2 | Spawned helper processes do not flash console windows | S | 2,3 | `docker`, `wsl`, `powershell` spawns use `CREATE_NO_WINDOW` on Windows (none today) | code review; *HW* |
| REL-3 | A defined, tested data path for upgrade | S | 4 | Documented: migrations run on start; volume preserved across reinstall | *HW* |

### Install and distribution (INS)

| ID | Requirement | Pri | UC | Acceptance criterion | Verify |
|---|---|---|---|---|---|
| INS-1 | WebView2 handling is explicit | S | 1 | `bundle.windows.webviewInstallMode` set deliberately (none today) | build + clean Win10 *HW* |
| INS-2 | One supported installer format decided | S | 1 | MSI vs NSIS choice recorded with reason | *HW* |
| INS-3 | Uninstall behavior for data is defined and documented | M | 5 | Docs say what happens to the Docker volume; no silent data loss | *HW* |
| INS-4 | Backup/restore path exists | M | 6 | Documented command or UI to export the DB | needs design |
| INS-5 | Update strategy decided | C | 4 | Decision recorded (#338); no updater plugin exists today | decision |

### Verification (VER)

| ID | Requirement | Pri | Acceptance criterion |
|---|---|---|---|
| VER-1 | A real-Windows test checklist exists and has been run once | M | Section 7 completed on a clean Win10/11 VM, results recorded |
| VER-2 | CI keeps building Windows bundles | S | Existing `build-windows` job stays green (build check only, not proof of runtime) |

## 5. Risk table

| Risk | Evidence | Impact | Covered by |
|---|---|---|---|
| Stack reachable from LAN | `deploy/docker-compose.yml`: `"5432:5432"`, `"8000:8000"` unprefixed; uvicorn on `0.0.0.0` | Anyone on the network can hit the API and Postgres | SEC-1, SEC-2 |
| Forgeable auth tokens | JWT falls back to a publicly known string | Token forgery against any install without `JWT_SECRET` | SEC-3 |
| Default DB password | `POSTGRES_PASSWORD: postgres` | Trivial DB access if exposed | SEC-2, SEC-4 |
| Unsigned installer | No Authenticode; `release.yml` ships unsigned Windows artifacts | SmartScreen warnings; no tamper evidence | SEC-7 |
| Console flashing / odd UX | no `creation_flags` anywhere in `tauri/src-tauri/src` | Looks broken to a non-technical owner | REL-2 |
| Untested error classification | no `#[test]` in `tauri/src-tauri/src` | Regressions in the first-run flow go unseen | REL-1 |
| Data trapped in WSL2 volume | named volume `postgres_data` | Data loss on Docker reset; no backup | INS-3, INS-4 |
| Windows origin never observed | CORS regex allows `http://tauri.localhost`, comment cites only Linux/Android | A CORS regression could break the app with no test failing | SEC-5 |

## 6. Plan and traceability

Each fix is its own PR, referencing the IDs above.

| Requirement | Planned change | Status |
|---|---|---|
| SEC-1, SEC-2 | loopback binding / drop Postgres port in `deploy/docker-compose.yml` | planned |
| SEC-3, SEC-4 | per-install secrets for the desktop path | planned (auth-critical, extra review) |
| SEC-5 | CORS test + comment fix | planned |
| REL-1 | Rust tests in `docker.rs` | planned |
| REL-2 | `CREATE_NO_WINDOW` under `cfg(windows)` | planned |
| INS-1 | `webviewInstallMode` in `tauri.conf.json` | planned |
| SEC-7 (checksums, docs) | `.sha256` + verify docs | planned |
| SEC-7 (Authenticode) | needs certificate and a key-handling decision against the "no keys in CI" policy | backlog (#229) |
| INS-2..5 | decisions / design | backlog |

## 7. Real-Windows verification checklist (not yet run)

On a clean Windows 10 and Windows 11 VM:

- [ ] Install via NSIS and via MSI; note SmartScreen/UAC behavior (UC-1)
- [ ] Launch with no Docker, with Docker stopped, with WSL2 absent, with virtualization off: confirm each error message (UC-2)
- [ ] Full happy path: stack starts, dashboard loads, an item can be created (UC-3)
- [ ] No console windows flash during launch (REL-2)
- [ ] Browser devtools/network confirm the origin is `http://tauri.localhost` and API calls pass CORS (SEC-5)
- [ ] From a second device on the LAN, `http://<pc-ip>:8000` and `:5432` are unreachable (SEC-1/2)
- [ ] Reinstall over an existing install: data survives (UC-4)
- [ ] Uninstall: record what happens to the Docker volume (UC-5)

## Caveats

This document is a first draft from a code read on a Linux host. Requirement
priorities are proposals for Sinan to adjust. Rows marked *HW* are untested
assumptions until section 7 is run.
