import { getServerHost, setServerHost } from "./config.js";

// No fallback -- unlike desktop, mobile has no address to guess (#232). An
// empty field just means "not configured yet"; #245's first-run flow is
// what decides what to do about that, not this page.
const form = document.getElementById("server-form");
const hostInput = document.getElementById("server-host");
const savedMessage = document.getElementById("server-saved");
const errorMessage = document.getElementById("server-error");

function handleSubmit(event) {
  event.preventDefault();
  savedMessage.classList.add("hidden");
  errorMessage.classList.add("hidden");

  const host = hostInput.value.trim();
  if (!host) {
    errorMessage.textContent = "Enter a server address.";
    errorMessage.classList.remove("hidden");
    return;
  }

  setServerHost(host);
  hostInput.value = getServerHost();
  savedMessage.classList.remove("hidden");
}

window.addEventListener("DOMContentLoaded", () => {
  const existing = getServerHost();
  if (existing) {
    hostInput.value = existing;
  }
  form.addEventListener("submit", handleSubmit);
});
