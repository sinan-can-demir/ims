use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus};
use std::time::{Duration, Instant};

const COMPOSE_FILE: &str = "deploy/docker-compose.yml";
const HEALTH_URL: &str = "http://localhost:8000/health";

pub enum DaemonStatus {
    NotInstalled,
    NotRunning,
    Running,
}

/// The IMS repo root, resolved relative to this crate at compile time.
/// Only valid for a `cargo tauri dev` / locally-built binary — packaging
/// (issue #195) will need Tauri's bundled-resource path resolution instead,
/// since a bundled app won't have `CARGO_MANIFEST_DIR`'s source layout.
pub fn project_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .expect("desktop/src-tauri/../.. should resolve to the repo root")
}

pub fn check_daemon() -> DaemonStatus {
    match Command::new("docker").arg("info").output() {
        Ok(output) if output.status.success() => DaemonStatus::Running,
        Ok(_) => DaemonStatus::NotRunning,
        Err(_) => DaemonStatus::NotInstalled,
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

pub fn compose_up(project_root: &Path) -> std::io::Result<ExitStatus> {
    compose_command(project_root)
        .args(["up", "-d", "--build"])
        .status()
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
