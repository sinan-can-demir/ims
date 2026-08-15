#[cfg(desktop)]
mod docker;

#[cfg(desktop)]
use std::path::Path;
#[cfg(desktop)]
use std::sync::Mutex;
#[cfg(desktop)]
use std::time::Duration;
#[cfg(desktop)]
use tauri::{AppHandle, Emitter, Manager};

// Bounded, but only the post-build window: once docker::compose_up()
// ("up -d", no --build -- see below) returns Started, db/migrate have
// already resolved via Compose's own depends_on conditions -- only
// api/dashboard binding and passing their own healthcheck is left, measured
// at ~10s in practice. 60s leaves real headroom without masking a genuinely
// stuck container as still "starting up".
#[cfg(desktop)]
const HEALTH_TIMEOUT: Duration = Duration::from_secs(60);

// Bounded, unlike docker::compose_build (deliberately unbounded -- see its
// own doc comment). Once images exist, `docker compose up -d` measured
// ~19-30s on the dev's own machine. 120s leaves generous headroom over that
// while still giving up on a genuinely stuck depends_on wait (e.g. a broken
// healthcheck) instead of hanging forever.
#[cfg(desktop)]
const START_TIMEOUT: Duration = Duration::from_secs(120);

#[cfg(desktop)]
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

// launch_stack starts racing the frontend's event listener the moment the
// window is created -- when Docker isn't even installed, checking for it
// fails near-instantly (a `CreateProcess` lookup failure), so `emit_phase`
// can fire and drop its *only* events before `main.js`'s DOMContentLoaded
// listener has registered. Caching the last phase here lets the frontend
// ask "what did I miss?" once it's actually listening, instead of freezing
// on the static "Starting..." placeholder forever with no error shown.
#[cfg(desktop)]
struct LastLaunchPhase(Mutex<Option<LaunchPhase>>);

#[cfg(desktop)]
#[tauri::command]
fn get_launch_phase(state: tauri::State<LastLaunchPhase>) -> Option<LaunchPhase> {
    state.0.lock().unwrap().clone()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|_app| {
            // Mobile has no local Docker daemon to launch -- the stack it
            // talks to runs on a remote desktop/server install (#227). Only
            // desktop owns its own lifecycle; mobile's frontend drives its
            // own first-run flow (#232/#245) instead of waiting on
            // "launch-phase" events that would otherwise never fire.
            #[cfg(desktop)]
            {
                _app.manage(LastLaunchPhase(Mutex::new(None)));
                let handle = _app.handle().clone();
                std::thread::spawn(move || launch_stack(handle));
            }
            Ok(())
        })
        .invoke_handler({
            #[cfg(desktop)]
            {
                tauri::generate_handler![get_launch_phase]
            }
            #[cfg(not(desktop))]
            {
                tauri::generate_handler![]
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|_app_handle, _event| {
            #[cfg(desktop)]
            if let tauri::RunEvent::Exit = _event {
                let root = docker::project_root(_app_handle);
                if let Err(err) = docker::compose_down(&root) {
                    eprintln!("failed to run docker compose down: {err}");
                }
            }
        });
}

#[cfg(desktop)]
fn emit_phase(handle: &AppHandle, phase: LaunchPhase) {
    *handle.state::<LastLaunchPhase>().0.lock().unwrap() = Some(phase.clone());
    // Best-effort: the frontend doesn't rely solely on this event arriving --
    // it also asks get_launch_phase for the cached copy above once its
    // listener is registered, to catch anything emitted before that point.
    let _ = handle.emit("launch-phase", phase);
}

#[cfg(desktop)]
fn port_conflict_message(conflicts: &[docker::PortConflict]) -> String {
    let details: Vec<String> =
        conflicts.iter().map(|c| format!("port {} ({})", c.port, c.label)).collect();
    format!("Another application is already using {}. Close it and try again.", details.join(", "))
}

/// When compose_up fails or times out, db failing its own healthcheck is a
/// specific, common enough cause (issue #194) to deserve a more actionable
/// message than the generic fallback -- and a pointer at the actual logs,
/// rather than a raw exit status a non-technical user can't act on.
#[cfg(desktop)]
fn compose_up_failure_message(root: &Path, fallback: String) -> String {
    match docker::db_health_status(root).as_deref() {
        Some("healthy") | None => fallback,
        Some(status) => format!(
            "The database container failed its health check (status: {status}). Run \
             `docker compose -f deploy/docker-compose.yml logs db` to see why."
        ),
    }
}

#[cfg(desktop)]
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
