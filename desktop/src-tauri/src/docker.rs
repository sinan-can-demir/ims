use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus};
use std::time::{Duration, Instant};
use tauri::{AppHandle, Manager};

const COMPOSE_FILE: &str = "deploy/docker-compose.yml";
const HEALTH_URL: &str = "http://localhost:8000/health";

pub enum DaemonStatus {
    NotInstalled,
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
pub fn project_root(handle: &AppHandle) -> PathBuf {
    if cfg!(debug_assertions) {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .expect("desktop/src-tauri/../.. should resolve to the repo root")
    } else {
        handle
            .path()
            .resource_dir()
            .expect("packaged app should have a resolvable resource directory")
            .join("repo")
    }
}

pub fn check_daemon() -> DaemonStatus {
    match Command::new("docker").arg("info").output() {
        Ok(output) if output.status.success() => DaemonStatus::Running,
        Ok(_) => DaemonStatus::NotRunning,
        Err(_) => DaemonStatus::NotInstalled,
    }
}

const SERVICE_PORTS: &[(&str, u16, &str)] =
    &[("db", 5432, "database"), ("api", 8000, "API"), ("dashboard", 8501, "dashboard")];

pub struct PortConflict {
    pub port: u16,
    pub label: &'static str,
}

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
fn compose_command(project_root: &Path) -> Command {
    let mut cmd = Command::new("docker");
    cmd.current_dir(project_root).args([
        "compose",
        "-f",
        COMPOSE_FILE,
        "--project-directory",
        ".",
    ]);
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
