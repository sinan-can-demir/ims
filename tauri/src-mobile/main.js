import { getServerHost, setServerHost, isLikelyTailscaleHost, getDashboardUrl } from "./config.js";

// No fallback -- unlike desktop, mobile has no address to guess (#232). An
// empty field just means "not configured yet".
const form = document.getElementById("server-form");
const hostInput = document.getElementById("server-host");
const savedMessage = document.getElementById("server-saved");
const errorMessage = document.getElementById("server-error");
const warningMessage = document.getElementById("server-warning");

// Mobile has no auth token of its own to manage. The dashboard's login
// (dashboard/auth.py) is a server-side Streamlit session, not a bearer
// token handed to the client -- there's nothing here to persist in a
// keychain, and nothing here to expire. This mirrors desktop's own
// pattern exactly (tauri/src/main.js's window.location.replace into the
// dashboard) minus desktop's bootstrap/register step, since mobile only
// ever logs into an already-bootstrapped server (#233's own "Why"). Once
// the webview navigates there, Streamlit's own login form and its
// built-in reconnect-on-reconnect handling (see #233's issue comment)
// own the rest -- backgrounding/foregrounding the app needs no extra
// code here, since the disconnected session lives on server-side with no
// expiry until the process is actually killed, matching how closing and
// reopening a laptop lid on the desktop app already behaves.
function goToDashboard() {
  const url = getDashboardUrl();
  if (url) {
    window.location.replace(url);
  }
}

function handleSubmit(event) {
  event.preventDefault();
  savedMessage.classList.add("hidden");
  errorMessage.classList.add("hidden");
  warningMessage.classList.add("hidden");

  const host = hostInput.value.trim();
  if (!host) {
    errorMessage.textContent = "Enter a server address.";
    errorMessage.classList.remove("hidden");
    return;
  }

  setServerHost(host);
  hostInput.value = getServerHost();

  // Saved either way (#269) -- but unlike the original settings-only
  // screen, saving now immediately navigates into the dashboard, and
  // navigating to a host that "will fail to connect" would just strand
  // the user on a blank/failed page with no way back to fix it (#245
  // hasn't built one yet) -- so this one warning does block the
  // navigation, while still leaving the value saved for editing.
  if (!isLikelyTailscaleHost(hostInput.value)) {
    warningMessage.textContent =
      "This doesn't look like a Tailscale address (myserver.tailnet-name.ts.net). " +
      "The app can only reach ts.net hosts over plain HTTP -- anything else will fail to connect.";
    warningMessage.classList.remove("hidden");
    savedMessage.classList.remove("hidden");
    return;
  }

  goToDashboard();
}

window.addEventListener("DOMContentLoaded", () => {
  const existing = getServerHost();
  if (existing) {
    // A host was already saved in a previous session -- go straight to
    // the dashboard instead of asking again. If it's stale or wrong, the
    // resulting page load fails visibly (fetch/navigation error in the
    // webview) rather than silently; getting back to this settings
    // screen to fix it is #245's own scope, not duplicated here.
    hostInput.value = existing;
    goToDashboard();
    return;
  }
  form.addEventListener("submit", handleSubmit);
});
