mod docker;

use std::path::Path;
use std::time::Duration;
use tauri::{AppHandle, Emitter};

// Bounded, but only the post-build window: once docker::compose_up()
// ("up -d", no --build -- see below) returns Started, db/migrate have
// already resolved via Compose's own depends_on conditions -- only
// api/dashboard binding and passing their own healthcheck is left, measured
// at ~10s in practice. 60s leaves real headroom without masking a genuinely
// stuck container as still "starting up".
const HEALTH_TIMEOUT: Duration = Duration::from_secs(60);

// Bounded, unlike docker::compose_build (deliberately unbounded -- see its
// own doc comment). Once images exist, `docker compose up -d` measured
// ~19-30s on the dev's own machine. 120s leaves generous headroom over that
// while still giving up on a genuinely stuck depends_on wait (e.g. a broken
// healthcheck) instead of hanging forever.
const START_TIMEOUT: Duration = Duration::from_secs(120);

#[derive(Clone, serde::Serialize)]
#[serde(tag = "phase", content = "detail", rename_all = "snake_case")]
enum LaunchPhase {
    CheckingDocker,
    BuildingImages,
    StartingServices,
    WaitingForHealth,
    Healthy,
    Failed(String),
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || launch_stack(handle));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                let root = docker::project_root(app_handle);
                if let Err(err) = docker::compose_down(&root) {
                    eprintln!("failed to run docker compose down: {err}");
                }
            }
        });
}

fn emit_phase(handle: &AppHandle, phase: LaunchPhase) {
    // Best-effort: if no window is listening yet, there's nothing more
    // useful to do than drop the event -- the frontend re-derives its state
    // from whichever event arrives next, not from a delivery guarantee.
    let _ = handle.emit("launch-phase", phase);
}

fn port_conflict_message(conflicts: &[docker::PortConflict]) -> String {
    let details: Vec<String> =
        conflicts.iter().map(|c| format!("port {} ({})", c.port, c.label)).collect();
    format!("Another application is already using {}. Close it and try again.", details.join(", "))
}

/// When compose_up fails or times out, db failing its own healthcheck is a
/// specific, common enough cause (issue #194) to deserve a more actionable
/// message than the generic fallback -- and a pointer at the actual logs,
/// rather than a raw exit status a non-technical user can't act on.
fn compose_up_failure_message(root: &Path, fallback: String) -> String {
    match docker::db_health_status(root).as_deref() {
        Some("healthy") | None => fallback,
        Some(status) => format!(
            "The database container failed its health check (status: {status}). Run \
             `docker compose -f deploy/docker-compose.yml logs db` to see why."
        ),
    }
}

fn launch_stack(handle: AppHandle) {
    emit_phase(&handle, LaunchPhase::CheckingDocker);
    match docker::check_daemon() {
        docker::DaemonStatus::NotInstalled => {
            emit_phase(&handle, LaunchPhase::Failed("Docker is not installed.".into()));
            return;
        }
        docker::DaemonStatus::NotRunning => {
            emit_phase(
                &handle,
                LaunchPhase::Failed("Docker is installed, but the daemon isn't running.".into()),
            );
            return;
        }
        docker::DaemonStatus::Running => {}
    }

    let root = docker::project_root(&handle);

    // Checked before compose_build, not just before compose_up, so a real
    // conflict fails fast -- no reason to make the user sit through a
    // possibly-many-minute build only to hit this at the very end.
    let conflicts = docker::check_port_conflicts(&root);
    if !conflicts.is_empty() {
        emit_phase(&handle, LaunchPhase::Failed(port_conflict_message(&conflicts)));
        return;
    }

    emit_phase(&handle, LaunchPhase::BuildingImages);
    match docker::compose_build(&root) {
        Ok(status) if status.success() => {}
        Ok(status) => {
            emit_phase(
                &handle,
                LaunchPhase::Failed(format!("docker compose build exited with {status}")),
            );
            return;
        }
        Err(err) => {
            emit_phase(
                &handle,
                LaunchPhase::Failed(format!("failed to run docker compose build: {err}")),
            );
            return;
        }
    }

    emit_phase(&handle, LaunchPhase::StartingServices);
    match docker::compose_up(&root, START_TIMEOUT) {
        Ok(docker::StartOutcome::Started) => {}
        Ok(docker::StartOutcome::Failed(status)) => {
            let fallback = format!("docker compose up exited with {status}");
            emit_phase(&handle, LaunchPhase::Failed(compose_up_failure_message(&root, fallback)));
            return;
        }
        Ok(docker::StartOutcome::TimedOut) => {
            let fallback = format!("Services did not start within {START_TIMEOUT:?}.");
            emit_phase(&handle, LaunchPhase::Failed(compose_up_failure_message(&root, fallback)));
            return;
        }
        Err(err) => {
            emit_phase(
                &handle,
                LaunchPhase::Failed(format!("failed to run docker compose up: {err}")),
            );
            return;
        }
    }

    emit_phase(&handle, LaunchPhase::WaitingForHealth);
    if docker::wait_for_health(HEALTH_TIMEOUT) {
        emit_phase(&handle, LaunchPhase::Healthy);
    } else {
        let fallback = format!("IMS did not become healthy within {HEALTH_TIMEOUT:?}.");
        emit_phase(&handle, LaunchPhase::Failed(compose_up_failure_message(&root, fallback)));
    }
}
