use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus};
use std::time::{Duration, Instant};
use tauri::{AppHandle, Manager};

const HEALTH_URL: &str = "http://localhost:8000/health";

pub enum DaemonStatus {
    NotInstalled,
    /// Windows-only: `docker info` failed and the CPU's virtualization
    /// firmware flag reads back positively disabled. Checked ahead of
    /// `Wsl2Missing` below since it's the more fundamental cause when both
    /// are true -- WSL2 itself can't install without it, so telling the user
    /// to fix BIOS/UEFI settings first avoids sending them through a WSL2
    /// install that's going to fail anyway (#262).
    VirtualizationDisabled,
    /// Windows-only: `docker info` failed and WSL2 (Docker Desktop's backend
    /// on Windows) isn't installed. Collapsing this into `NotRunning` would
    /// tell a non-technical user to "start Docker Desktop" when the actual
    /// fix is a separate Windows feature install + reboot (#262).
    Wsl2Missing,
    NotRunning,
    Running,
}

/// Where deploy/docker-compose.yml, docker/, app/, dashboard/, etc. live at
/// runtime -- the actual Docker build context. Two genuinely different
/// answers depending on how the binary is running:
///
/// - `cargo tauri dev`: the live source tree, via `CARGO_MANIFEST_DIR`
///   (baked in at compile time) -- so edits to app/ or dashboard/ are
///   picked up on the next launch without needing to re-bundle anything.
/// - A packaged build (.rpm/.AppImage, issue #195): `CARGO_MANIFEST_DIR`
///   would point at wherever *this binary* happened to be compiled --
///   meaningless, often nonexistent, on the end user's machine. Those
///   directories are bundled as Tauri resources instead (see
///   tauri.conf.json's bundle.resources, all mapped under "repo/"), and
///   `AppHandle::path().resource_dir()` resolves to wherever Tauri's
///   installer/AppImage actually put them at install/run time.
///
/// Gated on `cfg!(debug_assertions)` rather than a Tauri-specific "is dev"
/// check -- `cargo tauri dev` builds debug by default, `cargo tauri build`
/// builds release by default, which is the same distinction that already
/// matters here.
///
/// Both branches build the path via `Path`/`PathBuf` (`.join`,
/// `.canonicalize`), which use the platform separator automatically, so
/// this needs no Windows-specific handling (#226).
pub fn project_root(handle: &AppHandle) -> Result<PathBuf, String> {
    if cfg!(debug_assertions) {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .map_err(|e| format!("tauri/src-tauri/../.. did not resolve to the repo root: {e}"))
    } else {
        handle
            .path()
            .resource_dir()
            .map_err(|e| format!("could not resolve the app's resource directory: {e}"))
            .map(|dir| dir.join("repo"))
    }
}

// A few short retries before concluding the daemon is genuinely down --
// right after boot/login, Docker Desktop can still be starting up, and
// `docker info` failing in that window isn't the same problem as it being
// down for good (#262). 3 attempts / 2s apart gives real startup a few
// seconds of grace without making every launch wait on a fixed delay.
const DAEMON_CHECK_ATTEMPTS: u32 = 3;
const DAEMON_CHECK_RETRY_DELAY: Duration = Duration::from_secs(2);

/// On Windows, Docker Desktop's daemon listens on a named pipe rather than
/// a Unix socket, but the `docker` CLI itself abstracts that -- `docker
/// info`'s exit code means the same thing on both platforms as long as
/// Docker Desktop put `docker.exe` on PATH (its installer does this by
/// default). Assumes the WSL2 backend specifically (Docker Desktop's
/// default and only recommended Windows mode) -- Windows containers mode
/// is out of scope, see #226, since this stack's images are Linux-based.
pub fn check_daemon() -> DaemonStatus {
    for attempt in 0..DAEMON_CHECK_ATTEMPTS {
        match Command::new("docker").arg("info").output() {
            Ok(output) if output.status.success() => return DaemonStatus::Running,
            Ok(_) if attempt + 1 < DAEMON_CHECK_ATTEMPTS => {
                std::thread::sleep(DAEMON_CHECK_RETRY_DELAY);
            }
            Ok(_) => return classify_windows_failure(),
            Err(_) => return DaemonStatus::NotInstalled,
        }
    }
    unreachable!("loop above always returns before exhausting its attempts")
}

fn classify_windows_failure() -> DaemonStatus {
    if virtualization_disabled_in_firmware() == Some(true) {
        DaemonStatus::VirtualizationDisabled
    } else if wsl2_missing() {
        DaemonStatus::Wsl2Missing
    } else {
        DaemonStatus::NotRunning
    }
}

/// Gated on `target_os = "windows"` -- `wsl` isn't a thing to check for on
/// Linux/Mac, and `Command::new("wsl")` failing to spawn there would
/// otherwise misread a genuine "daemon just isn't running" as "WSL2
/// missing". On Windows, `wsl --status` exits non-zero (observed `1` on a
/// genuinely WSL-less machine, via `wsl.exe`'s own built-in fallback shim
/// that ships with Windows even when the "Windows Subsystem for Linux"
/// feature itself is off) when WSL2 isn't set up.
fn wsl2_missing() -> bool {
    if !cfg!(target_os = "windows") {
        return false;
    }
    !Command::new("wsl")
        .arg("--status")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

/// Gated on `target_os = "windows"` for the same reason as `wsl2_missing`.
/// `Win32_Processor.VirtualizationFirmwareEnabled` is the same CIM property
/// Windows' own "Turn Windows features on or off" dialog and Hyper-V's
/// compatibility check read -- queried directly (rather than via the much
/// broader, ~5s-latency `Get-ComputerInfo`, measured on real hardware) since
/// this only runs after `docker info` has already failed and shouldn't add
/// much more delay on top of that.
///
/// Returns `None` -- "can't tell" -- for every case except a confirmed
/// `False`: the property reads back empty once a hypervisor is already
/// active (observed on this dev VM itself, where a *nested* hypervisor
/// being absent from the guest's virtual firmware makes the flag read
/// `False` even with an outer hypervisor clearly present) or on older
/// Windows builds that don't expose it at all. A false "virtualization is
/// off" would send a user hunting through their BIOS for a problem that
/// doesn't exist, so treat anything ambiguous as "don't know" and fall
/// through to the next check instead of asserting it.
fn virtualization_disabled_in_firmware() -> Option<bool> {
    if !cfg!(target_os = "windows") {
        return None;
    }
    let output = Command::new("powershell")
        .args([
            "-NoProfile",
            "-Command",
            "(Get-CimInstance Win32_Processor -Property VirtualizationFirmwareEnabled \
             -ErrorAction SilentlyContinue).VirtualizationFirmwareEnabled",
        ])
        .output()
        .ok()?;
    match String::from_utf8_lossy(&output.stdout).trim() {
        "True" => Some(false),
        "False" => Some(true),
        _ => None,
    }
}

const SERVICE_PORTS: &[(&str, u16, &str)] =
    &[("db", 5432, "database"), ("api", 8000, "API"), ("dashboard", 8501, "dashboard")];

pub struct PortConflict {
    pub port: u16,
    pub label: &'static str,
}

// std::net::TcpListener::bind is a thin wrapper over the OS socket API on
// every platform Rust supports, including Windows, so the happy path here
// is identical. The one open question (#226) is a TIME_WAIT edge case:
// Windows and Linux don't default to the same bind-vs-TIME_WAIT-socket
// behavior, so a port that just closed could in theory read as "in use" on
// one platform and "free" on the other for a few seconds. Neither this
// function nor its caller sets SO_REUSEADDR (would need the `socket2`
// crate; std::net doesn't expose it), so this is unverified on real
// Windows rather than fixed -- flagging it here instead of guessing at a
// fix with no Windows machine to reproduce against.
fn port_is_free(port: u16) -> bool {
    std::net::TcpListener::bind(("127.0.0.1", port)).is_ok()
}

/// Which of our own services are already running for this compose project
/// — not JSON, just service names, one per line, so no need for a JSON
/// dependency just to read this.
fn running_services(project_root: &Path) -> Vec<String> {
    let output = compose_command(project_root)
        .args(["ps", "--status", "running", "--services"])
        .output();
    match output {
        Ok(out) if out.status.success() => String::from_utf8_lossy(&out.stdout)
            .lines()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string)
            .collect(),
        _ => Vec::new(),
    }
}

/// A port already held by *our own* already-running container (e.g. a
/// relaunch against a stack that never got torn down) isn't a conflict —
/// `docker compose up` recreates it cleanly. Only a port held by something
/// outside our own project is a real, actionable conflict (issue #174's
/// "why this matters": a stray unrelated process already bound to 8501).
pub fn check_port_conflicts(project_root: &Path) -> Vec<PortConflict> {
    let running = running_services(project_root);
    SERVICE_PORTS
        .iter()
        .filter(|(service, _, _)| !running.iter().any(|s| s == service))
        .filter(|(_, port, _)| !port_is_free(*port))
        .map(|(_, port, label)| PortConflict { port: *port, label })
        .collect()
}

/// db's healthcheck status ("healthy"/"unhealthy"/"starting"/...), used to
/// give a specific, actionable message when `compose_up` fails or times out
/// because db never became healthy — rather than the same generic "docker
/// compose up exited with ..." message regardless of cause.
pub fn db_health_status(project_root: &Path) -> Option<String> {
    let output = compose_command(project_root)
        .args(["ps", "db", "--format", "{{.Health}}"])
        .output()
        .ok()?;
    if output.status.success() {
        let status = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if status.is_empty() {
            None
        } else {
            Some(status)
        }
    } else {
        None
    }
}

// Mirrors scripts/ims.py's COMPOSE_ARGS: pin the project directory to the
// repo root (not deploy/, Compose's default for a -f-only invocation) so
// build context, bind mounts, .env resolution, and the Compose project name
// (container/volume naming) all match what `python scripts/ims.py` produces.
//
// The compose file path is built via `Path::join`, not a hardcoded
// forward-slash string -- `docker compose` on Windows does tolerate `/` in
// practice, but there's no reason to rely on that when `PathBuf` gives the
// platform-correct separator for free (#226). `Command::arg` takes anything
// `AsRef<OsStr>`, which `PathBuf` implements, so this passes through as-is.
fn compose_command(project_root: &Path) -> Command {
    let compose_file = Path::new("deploy").join("docker-compose.yml");
    let mut cmd = Command::new("docker");
    cmd.current_dir(project_root)
        .arg("compose")
        .arg("-f")
        .arg(compose_file)
        .args(["--project-directory", "."]);
    cmd
}

/// Deliberately unbounded — no timeout wraps this. #174 always runs a
/// rebuild on every launch, and killing a build partway through via a
/// timeout would leave Docker's build cache and possibly partially-created
/// layers in a worse state than just waiting, however long that takes
/// (measured ~49min for a genuine --no-cache cold build on the dev's own
/// machine — see #191/#193's HEALTH_TIMEOUT comment in lib.rs).
pub fn compose_build(project_root: &Path) -> std::io::Result<ExitStatus> {
    compose_command(project_root).arg("build").status()
}

pub enum StartOutcome {
    Started,
    Failed(ExitStatus),
    TimedOut,
}

/// Bounded, unlike compose_build above — once images exist, `up -d` just
/// creates/starts containers and waits on Compose's own depends_on
/// conditions (db healthcheck, migrate's one-off completion). That can
/// legitimately hang forever on a genuinely broken environment (e.g. a
/// stuck healthcheck), with nothing else timing it out, so this is the one
/// place in the launch sequence a Rust-side kill is actually the safer
/// choice, not the riskier one. Spawn + poll rather than `.status()`
/// (which has no way to time out) since Command has no native timeout.
pub fn compose_up(project_root: &Path, timeout: Duration) -> std::io::Result<StartOutcome> {
    let mut child = compose_command(project_root).args(["up", "-d"]).spawn()?;
    let deadline = Instant::now() + timeout;
    loop {
        if let Some(status) = child.try_wait()? {
            return Ok(if status.success() {
                StartOutcome::Started
            } else {
                StartOutcome::Failed(status)
            });
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Ok(StartOutcome::TimedOut);
        }
        std::thread::sleep(Duration::from_millis(500));
    }
}

pub fn compose_down(project_root: &Path) -> std::io::Result<ExitStatus> {
    compose_command(project_root).arg("down").status()
}

pub fn wait_for_health(timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        let reachable = ureq::get(HEALTH_URL)
            .timeout(Duration::from_secs(2))
            .call()
            .map(|resp| resp.status() == 200)
            .unwrap_or(false);
        if reachable {
            return true;
        }
        std::thread::sleep(Duration::from_secs(2));
    }
    false
}
