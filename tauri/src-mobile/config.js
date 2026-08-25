// Plain localStorage, not Tauri's store plugin -- this project's frontend
// has no bundler (index.html loads main.js as a raw ES module), so a bare
// npm-package import like "@tauri-apps/plugin-store" can't resolve at
// runtime in the actual webview: confirmed empirically, it throws
// "Failed to resolve module specifier" the moment the page loads on
// Android (#232). localStorage needs no import at all and is sufficient
// for persisting one string.
const SERVER_HOST_KEY = "ims_server_host";

// Fixed, not user-configurable: both desktop and mobile talk to the same
// docker-compose stack, which always binds the API and dashboard to these
// two ports (deploy/docker-compose.yml). Only the *host* varies -- desktop's
// is always its own machine, mobile's is a Tailscale address (#227/#232).
const API_PORT = 8000;
const DASHBOARD_PORT = 8501;

// Forgiving of a pasted full URL (e.g. "http://100.x.x.x:8000/") even
// though the settings screen only asks for a bare host -- cheap to accept,
// avoids a confusing failure for a copy-paste habit.
function normalizeHost(host) {
  return host
    .trim()
    .replace(/^https?:\/\//, "")
    .replace(/\/+$/, "")
    .replace(/:\d+$/, "");
}

// `fallback` is the bare host/IP to use when nothing's configured yet --
// desktop passes "localhost" (matching its previous hardcoded behavior);
// mobile passes undefined, since there's no address it could guess (#232).
export function getServerHost(fallback) {
  const stored = window.localStorage.getItem(SERVER_HOST_KEY);
  return stored && stored.length > 0 ? stored : fallback;
}

export function setServerHost(host) {
  window.localStorage.setItem(SERVER_HOST_KEY, normalizeHost(host));
}

// Returns null when no host is configured and no fallback was given --
// callers (mobile's settings/first-run flow) use that to know a server
// still needs to be configured, rather than silently hitting a bad URL.
export function getApiBase(fallbackHost) {
  const host = getServerHost(fallbackHost);
  return host ? `http://${host}:${API_PORT}/api` : null;
}

export function getDashboardUrl(fallbackHost) {
  const host = getServerHost(fallbackHost);
  return host ? `http://${host}:${DASHBOARD_PORT}` : null;
}

// Only *.ts.net (Tailscale's MagicDNS domain) is exempted from Android's
// cleartext block -- see gen/android/app/src/main/res/xml/
// network_security_config.xml. A raw Tailscale IP literal (100.64.0.0/10)
// would still be a "real" Tailscale address, but Android's Network
// Security Configuration has no CIDR/IP-range primitive to scope cleartext
// by (confirmed against the platform docs), only exact domains -- so a raw
// IP here would actually fail at the OS level, not just look unusual.
// Warns (never blocks, #269) so leaving the ts.net path is a conscious
// choice, not a silent connection failure with no explanation.
export function isLikelyTailscaleHost(host) {
  return /\.ts\.net$/i.test(normalizeHost(host));
}
