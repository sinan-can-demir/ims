mod docker;

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
        .run(|_app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                let root = docker::project_root();
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

    let root = docker::project_root();

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
            emit_phase(
                &handle,
                LaunchPhase::Failed(format!("docker compose up exited with {status}")),
            );
            return;
        }
        Ok(docker::StartOutcome::TimedOut) => {
            emit_phase(
                &handle,
                LaunchPhase::Failed(format!("Services did not start within {START_TIMEOUT:?}.")),
            );
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
        emit_phase(
            &handle,
            LaunchPhase::Failed(format!("IMS did not become healthy within {HEALTH_TIMEOUT:?}.")),
        );
    }
}
