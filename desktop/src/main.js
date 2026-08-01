const API_BASE = "http://localhost:8000/api";
const DASHBOARD_URL = "http://localhost:8501";
const POLL_INTERVAL_MS = 2000;

const statusMessage = document.getElementById("status-message");
const registerForm = document.getElementById("register-form");
const registerError = document.getElementById("register-error");

// No signal yet from the Rust side for "the stack is healthy" (that's
// issue #193) — polling this endpoint doubles as both "wait for the API to
// come up" and "check whether to show the wizard." A network error just
// means the stack (very likely still `docker compose up --build`ing) isn't
// reachable yet, so it's treated the same as "keep waiting," not a failure.
async function pollBootstrapStatus() {
  try {
    const response = await fetch(`${API_BASE}/auth/bootstrap-status`);
    if (!response.ok) {
      scheduleNextPoll();
      return;
    }
    const body = await response.json();
    if (body.needs_registration) {
      showRegisterForm();
    } else {
      window.location.replace(DASHBOARD_URL);
    }
  } catch {
    scheduleNextPoll();
  }
}

function scheduleNextPoll() {
  setTimeout(pollBootstrapStatus, POLL_INTERVAL_MS);
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
  registerForm.addEventListener("submit", handleRegisterSubmit);
  pollBootstrapStatus();
});
