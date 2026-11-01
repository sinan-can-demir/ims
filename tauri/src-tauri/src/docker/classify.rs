//! Pure decision/parsing logic behind docker.rs's environment checks --
//! everything that interprets `docker info`, `wsl --status`, the PowerShell
//! virtualization query, and `docker compose ps` output, with no process
//! spawning, sleeping, or Tauri dependency of its own (#366, REL-1).
//!
//! docker.rs still owns actually running those commands; it hands their
//! results to the functions here. Keeping the two apart is what makes the
//! Windows failure classification (#262) testable with plain `cargo test`
//! on Linux -- the logic is platform-independent once it isn't interleaved
//! with `Command::new("wsl")`/`Command::new("powershell")`.

use std::io;

#[derive(Debug, PartialEq, Eq)]
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

/// The retry loop behind `docker::check_daemon`, with each side effect
/// injected: `docker_info` runs `docker info` once (`Ok(success)`, or `Err`
/// if the binary couldn't be spawned at all), `wait` sleeps between
/// attempts, and `classify_failure` runs the (slow, Windows-only) diagnosis
/// once every attempt has failed.
///
/// A spawn error means `docker` isn't on PATH -- not something a retry can
/// fix, so it returns `NotInstalled` immediately on any attempt. `attempts`
/// below 1 is treated as 1: `docker info` always runs at least once.
pub fn check_daemon_with(
    attempts: u32,
    mut docker_info: impl FnMut() -> io::Result<bool>,
    mut wait: impl FnMut(),
    classify_failure: impl FnOnce() -> DaemonStatus,
) -> DaemonStatus {
    let mut attempt = 1;
    loop {
        match docker_info() {
            Ok(true) => return DaemonStatus::Running,
            Err(_) => return DaemonStatus::NotInstalled,
            Ok(false) if attempt < attempts => {
                wait();
                attempt += 1;
            }
            Ok(false) => return classify_failure(),
        }
    }
}

/// `virtualization_disabled` is `parse_virtualization_firmware`'s result
/// (`None` = can't tell); only a confirmed `Some(true)` wins over the WSL2
/// check, see `DaemonStatus::VirtualizationDisabled` for why it goes first.
/// `wsl2_missing` is lazy so a confirmed virtualization answer skips
/// spawning `wsl --status` entirely.
pub fn classify_failure(
    virtualization_disabled: Option<bool>,
    wsl2_missing: impl FnOnce() -> bool,
) -> DaemonStatus {
    if virtualization_disabled == Some(true) {
        DaemonStatus::VirtualizationDisabled
    } else if wsl2_missing() {
        DaemonStatus::Wsl2Missing
    } else {
        DaemonStatus::NotRunning
    }
}

/// Interprets the PowerShell `Win32_Processor.VirtualizationFirmwareEnabled`
/// query's stdout. Returns whether virtualization is *disabled* --
/// `Some(true)` only for an exact `False`, `None` ("can't tell") for
/// anything else.
///
/// The property reads back empty once a hypervisor is already active, and
/// older Windows builds don't expose it at all. A false "virtualization is
/// off" would send a user hunting through their BIOS for a problem that
/// doesn't exist, so anything ambiguous is "don't know" and falls through
/// to the next check instead of asserting it. That includes multi-line
/// output (one line per CPU socket on a multi-socket machine) -- left as
/// "can't tell" rather than guessed at, matching the behavior before this
/// logic was extracted.
pub fn parse_virtualization_firmware(stdout: &str) -> Option<bool> {
    match stdout.trim() {
        "True" => Some(false),
        "False" => Some(true),
        _ => None,
    }
}

/// Interprets `wsl --status`: `Ok(success)` from running it, `Err` if
/// `wsl.exe` couldn't be spawned. On a genuinely WSL-less machine it exits
/// non-zero (observed `1`, via `wsl.exe`'s own built-in fallback shim that
/// ships with Windows even when the "Windows Subsystem for Linux" feature
/// itself is off). Failing to spawn it at all is treated as missing too.
pub fn wsl2_missing_from(status: io::Result<bool>) -> bool {
    !status.unwrap_or(false)
}

/// (compose service, host port, user-facing label) for every port the
/// stack publishes.
const SERVICE_PORTS: &[(&str, u16, &str)] = &[
    ("db", 5432, "database"),
    ("api", 8000, "API"),
    ("dashboard", 8501, "dashboard"),
];

#[derive(Debug, PartialEq, Eq)]
pub struct PortConflict {
    pub port: u16,
    pub label: &'static str,
}

/// Parses `docker compose ps --status running --services` -- not JSON,
/// just service names, one per line, so no need for a JSON dependency just
/// to read this. Trims each line, so Windows' `\r\n` line endings parse
/// the same as `\n`.
pub fn parse_running_services(stdout: &str) -> Vec<String> {
    stdout
        .lines()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .collect()
}

/// A port already held by *our own* already-running container (e.g. a
/// relaunch against a stack that never got torn down) isn't a conflict --
/// `docker compose up` recreates it cleanly. Only a port held by something
/// outside our own project is a real, actionable conflict (issue #174's
/// "why this matters": a stray unrelated process already bound to 8501).
/// `port_is_free` is only consulted for services not already running.
pub fn find_port_conflicts(
    running: &[String],
    port_is_free: impl Fn(u16) -> bool,
) -> Vec<PortConflict> {
    SERVICE_PORTS
        .iter()
        .filter(|(service, _, _)| !running.iter().any(|s| s == service))
        .filter(|(_, port, _)| !port_is_free(*port))
        .map(|(_, port, label)| PortConflict { port: *port, label })
        .collect()
}

/// Parses `docker compose ps db --format {{.Health}}` -- `None` when empty
/// (container doesn't exist, or has no healthcheck).
pub fn parse_db_health(stdout: &str) -> Option<String> {
    let status = stdout.trim();
    if status.is_empty() {
        None
    } else {
        Some(status.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;

    fn spawn_error() -> io::Error {
        io::Error::new(io::ErrorKind::NotFound, "program not found")
    }

    // ---- check_daemon_with ----

    #[test]
    fn daemon_running_on_first_attempt() {
        let calls = Cell::new(0);
        let waits = Cell::new(0);
        let status = check_daemon_with(
            3,
            || {
                calls.set(calls.get() + 1);
                Ok(true)
            },
            || waits.set(waits.get() + 1),
            || panic!("must not classify when docker info succeeds"),
        );
        assert_eq!(status, DaemonStatus::Running);
        assert_eq!(calls.get(), 1);
        assert_eq!(waits.get(), 0);
    }

    #[test]
    fn daemon_still_starting_then_running() {
        // Docker Desktop still coming up right after login (#262): early
        // failures followed by success must not be reported as a failure.
        let calls = Cell::new(0);
        let waits = Cell::new(0);
        let status = check_daemon_with(
            3,
            || {
                calls.set(calls.get() + 1);
                Ok(calls.get() == 3)
            },
            || waits.set(waits.get() + 1),
            || panic!("must not classify when a retry succeeds"),
        );
        assert_eq!(status, DaemonStatus::Running);
        assert_eq!(calls.get(), 3);
        assert_eq!(waits.get(), 2);
    }

    #[test]
    fn docker_not_on_path_is_not_installed_without_retrying() {
        let calls = Cell::new(0);
        let status = check_daemon_with(
            3,
            || {
                calls.set(calls.get() + 1);
                Err(spawn_error())
            },
            || panic!("must not wait after a spawn error"),
            || panic!("must not classify after a spawn error"),
        );
        assert_eq!(status, DaemonStatus::NotInstalled);
        assert_eq!(calls.get(), 1);
    }

    #[test]
    fn spawn_error_on_a_later_attempt_is_still_not_installed() {
        let calls = Cell::new(0);
        let status = check_daemon_with(
            3,
            || {
                calls.set(calls.get() + 1);
                if calls.get() == 1 {
                    Ok(false)
                } else {
                    Err(spawn_error())
                }
            },
            || {},
            || panic!("must not classify after a spawn error"),
        );
        assert_eq!(status, DaemonStatus::NotInstalled);
    }

    #[test]
    fn every_attempt_failing_hands_off_to_classification() {
        let calls = Cell::new(0);
        let waits = Cell::new(0);
        let status = check_daemon_with(
            3,
            || {
                calls.set(calls.get() + 1);
                Ok(false)
            },
            || waits.set(waits.get() + 1),
            || DaemonStatus::Wsl2Missing,
        );
        assert_eq!(status, DaemonStatus::Wsl2Missing);
        assert_eq!(calls.get(), 3);
        // No pointless sleep after the final attempt.
        assert_eq!(waits.get(), 2);
    }

    #[test]
    fn zero_attempts_still_runs_docker_info_once() {
        let calls = Cell::new(0);
        let status = check_daemon_with(
            0,
            || {
                calls.set(calls.get() + 1);
                Ok(false)
            },
            || panic!("must not wait with no attempts left"),
            || DaemonStatus::NotRunning,
        );
        assert_eq!(status, DaemonStatus::NotRunning);
        assert_eq!(calls.get(), 1);
    }

    // ---- classify_failure ----

    #[test]
    fn virtualization_disabled_wins_without_checking_wsl() {
        let status = classify_failure(Some(true), || {
            panic!("must not run wsl --status once decided")
        });
        assert_eq!(status, DaemonStatus::VirtualizationDisabled);
    }

    #[test]
    fn wsl2_missing_when_virtualization_enabled_or_unknown() {
        assert_eq!(
            classify_failure(Some(false), || true),
            DaemonStatus::Wsl2Missing
        );
        assert_eq!(classify_failure(None, || true), DaemonStatus::Wsl2Missing);
    }

    #[test]
    fn not_running_when_nothing_else_explains_it() {
        assert_eq!(
            classify_failure(Some(false), || false),
            DaemonStatus::NotRunning
        );
        // Linux/macOS path: both Windows checks are gated off and report
        // "can't tell"/"not missing".
        assert_eq!(classify_failure(None, || false), DaemonStatus::NotRunning);
    }

    // ---- parse_virtualization_firmware ----

    #[test]
    fn virtualization_true_means_not_disabled() {
        assert_eq!(parse_virtualization_firmware("True"), Some(false));
    }

    #[test]
    fn virtualization_false_means_disabled() {
        assert_eq!(parse_virtualization_firmware("False"), Some(true));
    }

    #[test]
    fn virtualization_parsing_tolerates_powershell_line_endings() {
        assert_eq!(parse_virtualization_firmware("True\r\n"), Some(false));
        assert_eq!(parse_virtualization_firmware("  False\r\n"), Some(true));
    }

    #[test]
    fn virtualization_empty_output_is_unknown() {
        // Hypervisor already active, or property not exposed.
        assert_eq!(parse_virtualization_firmware(""), None);
        assert_eq!(parse_virtualization_firmware("\r\n"), None);
    }

    #[test]
    fn virtualization_unexpected_output_is_unknown() {
        assert_eq!(parse_virtualization_firmware("false"), None);
        assert_eq!(parse_virtualization_firmware("Yes"), None);
        assert_eq!(
            parse_virtualization_firmware("Get-CimInstance : Access denied\r\n"),
            None
        );
        // One line per CPU socket on a multi-socket machine.
        assert_eq!(parse_virtualization_firmware("True\r\nTrue\r\n"), None);
        assert_eq!(parse_virtualization_firmware("False\r\nFalse\r\n"), None);
    }

    // ---- wsl2_missing_from ----

    #[test]
    fn wsl_status_success_means_present() {
        assert!(!wsl2_missing_from(Ok(true)));
    }

    #[test]
    fn wsl_status_nonzero_exit_means_missing() {
        assert!(wsl2_missing_from(Ok(false)));
    }

    #[test]
    fn wsl_exe_failing_to_spawn_means_missing() {
        assert!(wsl2_missing_from(Err(spawn_error())));
    }

    // ---- parse_running_services / find_port_conflicts ----

    #[test]
    fn running_services_parsed_one_per_line() {
        assert_eq!(parse_running_services("db\napi\n"), vec!["db", "api"]);
    }

    #[test]
    fn running_services_tolerates_crlf_and_blank_lines() {
        assert_eq!(
            parse_running_services("db\r\n\r\n  api  \r\n"),
            vec!["db", "api"]
        );
        assert!(parse_running_services("").is_empty());
    }

    #[test]
    fn no_conflicts_when_every_port_is_free() {
        assert!(find_port_conflicts(&[], |_| true).is_empty());
    }

    #[test]
    fn busy_port_with_our_service_not_running_is_a_conflict() {
        let conflicts = find_port_conflicts(&[], |port| port != 8501);
        assert_eq!(
            conflicts,
            vec![PortConflict {
                port: 8501,
                label: "dashboard"
            }]
        );
    }

    #[test]
    fn busy_port_held_by_our_own_running_service_is_not_a_conflict() {
        let running = parse_running_services("dashboard\n");
        let conflicts = find_port_conflicts(&running, |port| port != 8501);
        assert!(conflicts.is_empty());
    }

    #[test]
    fn port_check_skipped_for_services_already_running() {
        let running = vec!["db".to_string(), "api".to_string(), "dashboard".to_string()];
        let conflicts = find_port_conflicts(&running, |_| panic!("must not probe our own ports"));
        assert!(conflicts.is_empty());
    }

    #[test]
    fn every_conflict_reported_in_service_order() {
        let conflicts = find_port_conflicts(&["api".to_string()], |_| false);
        assert_eq!(
            conflicts,
            vec![
                PortConflict {
                    port: 5432,
                    label: "database"
                },
                PortConflict {
                    port: 8501,
                    label: "dashboard"
                },
            ]
        );
    }

    // ---- parse_db_health ----

    #[test]
    fn db_health_status_trimmed() {
        assert_eq!(
            parse_db_health("unhealthy\r\n").as_deref(),
            Some("unhealthy")
        );
        assert_eq!(parse_db_health("healthy\n").as_deref(), Some("healthy"));
    }

    #[test]
    fn db_health_empty_is_none() {
        assert_eq!(parse_db_health(""), None);
        assert_eq!(parse_db_health("\r\n"), None);
    }
}
