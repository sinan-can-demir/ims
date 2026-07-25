# Security Policy

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, use [GitHub's private security advisory feature](../../security/advisories/new)
for this repository, or contact the maintainer directly through their GitHub
profile. You should get an acknowledgement within a few days — this is a
solo-maintained project, so response times aren't guaranteed to be fast, but
reports are taken seriously.

## Known limitations of the current auth model

IMS uses a single shared API key (`X-API-Key` header, checked in
`app/core/auth.py`) rather than per-user credentials, OAuth, or JWTs. This is a
deliberate, minimal design for the project's current stage, **not** a
production-grade auth system. Specifically:

- **One key for every client.** There's no per-user identity, no scoping, and
  no way to revoke a single caller's access without rotating the key for
  everyone.
- **Auth is a no-op if `API_KEY` is unset.** This is intentional for local
  development (`.env.example` documents it), but it means **you must set
  `API_KEY` before exposing this app on any network you don't fully trust**.
  A startup log line (`AUTH DISABLED — API_KEY not set`) warns loudly if the
  app boots without it, precisely so this isn't easy to miss in a deployed
  environment's logs.
- **The comparison is constant-time** (`hmac.compare_digest`), so the auth
  check itself isn't vulnerable to a timing attack — but that only protects
  the comparison, not the broader single-shared-secret design above.

If you need per-user auth, OAuth, or anything beyond "one shared secret keeps
casual/opportunistic access out," this project isn't there yet — see
[`ROADMAP.md`](ROADMAP.md) (Epoch 7) for what's planned.

## Webhook signature verification

`POST /api/webhooks/ingest` (see [`ROADMAP.md`](ROADMAP.md) Epoch 7.2) uses a
separate mechanism from `X-API-Key`: an `X-Webhook-Signature` header holding
an HMAC-SHA256 digest of the raw request body, keyed by the `WEBHOOK_SECRET`
env var (`app/core/auth.py`'s `require_webhook_signature`). Same shape and
same limitations as the API key above — one shared secret, no-op if unset
(local dev only), constant-time comparison via `hmac.compare_digest`.

## Rate limiting

`/api` routes (products, inventory, forecast — anything behind
`require_api_key`) are rate-limited via `slowapi`
(`app/core/rate_limit.py`), keyed by client IP. Default limit is
`100/minute`, configurable via the `RATE_LIMIT` env var. Limit exceeded
returns `429`. `/health`, `/metrics`, and `/api/webhooks/ingest`
(signature-verified, separate trust boundary — see below) are exempt.

Keying is by IP only, deliberately — not by the presented `X-API-Key`
value. IMS has exactly one valid shared key, so there's no per-client
identity to preserve, and keying by presented value would let an attacker
reset their bucket on every request just by guessing a different key each
time.

**Known limitation:** the default `memory://` storage backend is
per-process, not shared across Gunicorn's worker processes in production
(`WEB_CONCURRENCY`, `docker-compose.prod.yml` — same gap
`PROMETHEUS_MULTIPROC_DIR` exists to solve for `/metrics`). The effective
limit in prod is therefore roughly `WEB_CONCURRENCY x RATE_LIMIT`, not
exactly `RATE_LIMIT`. Divide `RATE_LIMIT` by your worker count if you need
the exact ceiling; a shared backend (e.g. Redis) would fix this properly
but isn't in place yet.

**Known limitation, latent as of 2026-07-24:** rate limiting depends on
`slowapi` (0.1.10, the latest release on PyPI), which finds each request's
route handler by scanning `app.routes` directly. FastAPI 0.140.0 changed
`include_router()` to wrap routes in a private `_IncludedRouter` object
instead of flattening them, which slowapi's lookup doesn't recognize —
the result isn't an error, rate limiting just silently stops applying to
every `/api` route. Currently not an issue (`requirements.txt` pins
`fastapi==0.135.2`), but **do not bump fastapi past 0.140.0 without
resolving [#66](https://github.com/sinan-can-demir/ims-manual/issues/66)
first** — a Dependabot PR proposing exactly that bump (#62) is intentionally
being held for this reason rather than merged.

## Response security headers

Every response gets `X-Content-Type-Options: nosniff`, `X-Frame-Options:
DENY`, and `Referrer-Policy: no-referrer` (`app/core/security_headers.py`).
`Strict-Transport-Security` is added only when the request arrived over
HTTPS (detected via `X-Forwarded-Proto`, set by both Caddy and AWS's ALB) —
uvicorn itself always sees plain HTTP, since TLS is terminated upstream, so
asserting HSTS unconditionally would break local dev and the no-domain
plain-HTTP self-hosted path. Neither Caddy nor the ALB add these headers on
their own; `Caddyfile` is a bare `reverse_proxy`.

## Dependency & vulnerability scanning

CI (`.github/workflows/ci.yml`'s `scan` job) runs on every push and PR, and
gates deployment alongside the other jobs:

- **Dependabot** (`.github/dependabot.yml`) opens PRs for outdated Python
  (pip), Docker base image, and GitHub Actions dependencies on a weekly
  schedule.
- **gitleaks** scans the PR's commits for accidentally committed secrets.
- **pip-audit** checks `requirements.txt` against known Python CVE databases.
- **trivy** scans the built Docker image for CRITICAL/HIGH OS and language
  package vulnerabilities (`--ignore-unfixed`, so it only blocks on issues
  with an available fix). A small number of findings that live in the
  pinned base image's own unused system Python packaging tools (not on the
  container's `PATH`) are suppressed via `.trivyignore`, each with an
  inline justification — that file should stay short and reviewed
  periodically, not become a dumping ground.

A green `scan` job is a real signal, not just a checkbox — Dependabot PRs
that pass it are safe to merge without manual review for low-risk
(patch/minor) bumps; major-version bumps and anything CI actually flags
still deserve a human look (see #62/#66 above for what that caught in
practice).

## Dashboard access

The Streamlit dashboard (`dashboard/app.py`) talks to the database directly
via the service layer — it doesn't go through `/api` and has none of the
`X-API-Key` protection above. It has no auth of its own at all. In the
self-hosted deployment path, its container port is never published by
default; it's only reachable once the Caddy overlay
(`docker-compose.caddy.yml`) fronts it with HTTP basic auth on a dedicated
HTTPS listener (`https://<DOMAIN>:8501`) — see
[`docs/deployment/self-hosted.md`](docs/deployment/self-hosted.md). Same
caveat as above: basic auth here is one shared username/password, not
per-user identity.

## Prior security review

[`docs/archive/report.md`](docs/archive/report.md) is a point-in-time AI code
review from an earlier stage of the project. Most of its findings have since
been addressed (see the commit history around `feat(auth)`), but it's kept as
project history rather than updated in place — it's not a live status report.
