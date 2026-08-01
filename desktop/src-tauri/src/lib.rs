mod docker;

use std::time::Duration;

// This only bounds the post-startup health poll, not the build. The build
// itself (docker::compose_up, below) is a plain blocking subprocess call
// with no timeout of its own — it just takes as long as `docker compose
// up -d --build` needs, measured on the dev's own machine at ~49 minutes
// for a genuine --no-cache cold build. That's the number scripts/ims.py's
// old 60s figure never accounted for (it predates #174's every-launch
// --build). Once compose_up() returns, though, db/migrate have already
// resolved via Compose's own depends_on conditions — only api/dashboard
// binding and passing their own healthcheck is left, measured at ~10s.
// 60s leaves real headroom over that without masking a genuinely stuck
// container as still "starting up".
const HEALTH_TIMEOUT: Duration = Duration::from_secs(60);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|_app| {
            std::thread::spawn(launch_stack);
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

fn launch_stack() {
    match docker::check_daemon() {
        docker::DaemonStatus::NotInstalled => {
            eprintln!("Docker is not installed.");
            return;
        }
        docker::DaemonStatus::NotRunning => {
            eprintln!("Docker is installed, but the daemon isn't running.");
            return;
        }
        docker::DaemonStatus::Running => {}
    }

    let root = docker::project_root();

    println!("Starting IMS stack (docker compose up -d --build)...");
    match docker::compose_up(&root) {
        Ok(status) if status.success() => {}
        Ok(status) => {
            eprintln!("docker compose up exited with {status}");
            return;
        }
        Err(err) => {
            eprintln!("failed to run docker compose up: {err}");
            return;
        }
    }

    println!("Waiting for API health check ({HEALTH_TIMEOUT:?} budget)...");
    if docker::wait_for_health(HEALTH_TIMEOUT) {
        println!("IMS is healthy.");
    } else {
        eprintln!("IMS did not become healthy within {HEALTH_TIMEOUT:?}.");
    }
}
