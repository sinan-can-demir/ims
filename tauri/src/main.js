import { getApiBase, getDashboardUrl } from "./config.js";

// Desktop always launches its own local stack (lib.rs's launch_stack), so
// unlike mobile it has a safe default to fall back on when nothing's been
// explicitly configured yet -- preserves the old hardcoded behavior (#232).
const DESKTOP_DEFAULT_HOST = "localhost";

let API_BASE;
let DASHBOARD_URL;

const BOOTSTRAP_STATUS_MAX_ATTEMPTS = 5;
const BOOTSTRAP_STATUS_RETRY_DELAY_MS = 400;

const statusMessage = document.getElementById("status-message");
const failureMessage = document.getElementById("failure-message");
const registerForm = document.getElementById("register-form");
const registerError = document.getElementById("register-error");

const PHASE_LABELS = {
  checking_docker: "Checking Docker...",
  building_images: "Building images (this can take a while on first run)...",
  starting_services: "Starting services...",
  waiting_for_health: "Waiting for IMS to respond...",
};

// Set once a launch-phase event (live or caught up via get_launch_phase,
// see below) has actually updated the UI -- guards against a delayed
// catch-up response clobbering a newer phase a live event already applied.
let phaseHandled = false;

// Driven by real phase events from the Rust side (desktop/src-tauri/src/
// lib.rs's launch_stack) rather than blindly polling and hoping, like the
// wizard did before this landed.
function handleLaunchPhase(event) {
  phaseHandled = true;
  const { phase, detail } = event.payload;

  if (phase === "failed") {
    showFailure(detail);
    return;
  }

  if (phase === "healthy") {
    statusMessage.textContent = "IMS is ready.";
    checkBootstrapStatus();
    return;
  }

  statusMessage.textContent = PHASE_LABELS[phase] ?? "Starting...";
}

function showFailure(message) {
  statusMessage.classList.add("hidden");
  failureMessage.textContent = message;
  failureMessage.classList.remove("hidden");
}

// "healthy" only means Rust's own HTTP client (ureq, not the webview's)
// successfully reached the API -- it says nothing about whether
// WebKitGTK's separate network stack has finished initializing yet.
// Confirmed by direct instrumentation: fetch() here can throw "Load
// failed" for a brief window immediately after "healthy" fires, even
// though the API is already answering curl/ureq requests fine at that
// exact moment -- a handful of quick retries absorbs that gap.
async function checkBootstrapStatus(attempt = 1) {
  try {
    const response = await fetch(`${API_BASE}/auth/bootstrap-status`);
    if (!response.ok) {
      showFailure("Could not check IMS's account status. Please restart the app.");
      return;
    }
    const body = await response.json();
    if (body.needs_registration) {
      showRegisterForm();
    } else {
      window.location.replace(DASHBOARD_URL);
    }
  } catch {
    if (attempt < BOOTSTRAP_STATUS_MAX_ATTEMPTS) {
      setTimeout(() => checkBootstrapStatus(attempt + 1), BOOTSTRAP_STATUS_RETRY_DELAY_MS);
      return;
    }
    showFailure("Could not reach IMS. Please restart the app.");
  }
}

function showRegisterForm() {
  statusMessage.classList.add("hidden");
  registerForm.classList.remove("hidden");
}

async function handleRegisterSubmit(event) {
  event.preventDefault();
  registerError.classList.add("hidden");

  const email = document.getElementById("register-email").value;
  const displayName = document.getElementById("register-display-name").value;
  const password = document.getElementById("register-password").value;

  try {
    const response = await fetch(`${API_BASE}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, display_name: displayName }),
    });

    if (response.ok) {
      window.location.replace(DASHBOARD_URL);
      return;
    }

    const body = await response.json().catch(() => null);
    registerError.textContent =
      typeof body?.detail === "string" ? body.detail : "Registration failed. Please try again.";
    registerError.classList.remove("hidden");
  } catch {
    registerError.textContent = "Could not reach IMS. Please try again.";
    registerError.classList.remove("hidden");
  }
}

window.addEventListener("DOMContentLoaded", () => {
  API_BASE = getApiBase(DESKTOP_DEFAULT_HOST);
  DASHBOARD_URL = getDashboardUrl(DESKTOP_DEFAULT_HOST);
  registerForm.addEventListener("submit", handleRegisterSubmit);
  window.__TAURI__.event.listen("launch-phase", handleLaunchPhase);

  // launch_stack (Rust) starts running before this listener exists, and on
  // a fast failure (e.g. Docker isn't even installed) can emit its only
  // events into the void -- best-effort emit doesn't queue them for a
  // listener that shows up later. Ask Rust what actually happened so we
  // don't sit on the static "Starting..." placeholder forever.
  window.__TAURI__.core.invoke("get_launch_phase").then((phase) => {
    if (!phaseHandled && phase) {
      handleLaunchPhase({ payload: phase });
    }
  });
});
