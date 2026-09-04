# Security Policy

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, use [GitHub's private security advisory feature](../../security/advisories/new)
for this repository, or contact the maintainer directly through their GitHub
profile. You should get an acknowledgement within a few days — this is a
solo-maintained project, so response times aren't guaranteed to be fast, but
reports are taken seriously.

## Auth model

IMS uses per-user accounts and JWT bearer tokens (`app/core/auth.py`,
`app/models/user.py`), not a single shared API key. `POST /api/auth/login`
verifies email/password (bcrypt, `app/core/security.py`) and issues a
signed JWT (HS256, 12-hour expiry, no refresh tokens); every other `/api`
route requires `Authorization: Bearer <token>`, validated by
`require_current_user`. Specifically:

- **Real per-user identity, with two roles: `admin` and `member`.** Every
  account defaults to `member`; `POST /api/inventory/replay` and
  `POST /api/inventory/export` require `admin` (`require_role`,
  `app/core/auth.py`), everything else just requires being logged in. Role
  isn't in the JWT — `require_role` re-reads the live `User.role` on every
  request via `require_current_user`, same convention as `is_active`, so a
  promotion or demotion takes effect immediately with the same
  still-unexpired token, no re-login required. Deactivating an account
  (`is_active=False`) takes effect immediately for the same reason.
- **`POST /api/inventory/export` is whole-deployment, not org-scoped —
  an accepted, deliberate gap, not an oversight.** There's no
  platform-operator role distinct from org-admin (still just the two
  roles above), so any org's admin who can hit this route exports
  every org's inventory events, not just their own. Replay
  (`/api/inventory/replay`) had the identical shape and *was* scoped
  per-org during Epoch 10 (see `docs/multi-tenancy.md`'s "Webhook
  ingestion"/analytics-pipeline sections) — export was deliberately
  left whole-deployment because its checkpoint is a single global
  `InventoryEvent.id` high-water mark shared by every org, and
  splitting that into a real per-org checkpoint (plus the `make export`
  cron path's own whole-deployment assumption) was out of scope for the
  PR that removed the dashboard's own export button (Epoch 10 PR 13,
  #149). Revisit if a real multi-org self-hosted deployment ever makes
  this matter in practice; see `docs/multi-tenancy.md` for the full
  writeup of what's org-scoped where.
- **Self-service registration is bootstrap-only, not general-purpose.**
  `POST /api/auth/register` (added for the desktop installer's first-run
  wizard, #189 — no self-service `getpass` equivalent existed for a GUI
  caller) only succeeds while `organization_id=1` has zero users;
  hardcodes `role=admin` and `organization_id=1` (no client-settable
  role or org), and is race-safe via `with_for_update()` on the
  organization row rather than a naive count-then-insert, so two
  concurrent first-run requests can't both create an account. Every
  account after that first one is still CLI-only via
  `scripts/create_user.py --role {admin,member}` (default `member`);
  `scripts/set_user_role.py` promotes/demotes an existing account and
  writes an `audit_log` entry (`action="role_changed"`) — the one
  account-related action that's audited, since it's a
  privilege-escalation event, unlike account creation.
- **Login failures are generic.** Unknown email, wrong password, and a
  deactivated account all return the same `401 Invalid email or password`
  — no signal about which case occurred, so an attacker can't use the
  login endpoint to enumerate valid emails.
- **`JWT_SECRET` can't be "disabled" the way the old `API_KEY` could.**
  Signing a JWT always requires a key, so an unset `JWT_SECRET` falls back
  to a fixed, publicly-known dev-only string instead of turning auth off —
  a startup log line warns loudly if the app boots without it set,
  precisely so this isn't easy to miss in a deployed environment's logs.
  **You must set `JWT_SECRET` before exposing this app on any network you
  don't fully trust.**
- **No server-side session storage or revocation list.** A token is valid
  for its full 12-hour lifetime once issued, unless the underlying user is
  deactivated. Not justified at this project's size yet; would need
  revisiting before this app has meaningfully sensitive data or more than
  a handful of users.

If you need OAuth/OIDC or anything beyond a two-role (`admin`/`member`)
model, this project isn't there yet — see [`ROADMAP.md`](ROADMAP.md) for
what's planned.

## Webhook signature verification

`POST /api/webhooks/{organization_id}/ingest` (see [`ROADMAP.md`](ROADMAP.md)
Epoch 7.2, redesigned per-org in Epoch 10 PR 12/#148) uses a separate
mechanism from the bearer-token auth above: an `X-Webhook-Signature` header
holding an HMAC-SHA256 digest of the raw request body, keyed by the target
org's own `organizations.webhook_secret` column (`app/core/auth.py`'s
`require_webhook_signature`) — not a single global env var. A shared secret
across every org would let any one org's webhook credential post events
into any other org, so each org's secret only ever authenticates requests
to that org's own `{organization_id}` in the path. `webhook_secret` is
`NOT NULL` — every org is provisioned with a real random secret at
creation time (`scripts/create_organization.py`, `secrets.token_hex(32)`),
and the endpoint fails closed (`401`) if it's ever unset, rather than
treating that as "verification disabled." (Before 2026-09, `NULL` was
treated as disabled and no provisioning path ever set the value — every
org in every deployment had unauthenticated ingest by default. See the
migration that backfilled existing rows and `scripts/rotate_webhook_secret.py`
for issuing a new secret if the original is lost.) Same constant-time
comparison via `hmac.compare_digest` either way.

Also rate-limited independently of the `/api` limit below —
`enforce_webhook_rate_limit` (`app/core/rate_limit.py`), keyed by the
target `organization_id` rather than client IP, since webhook senders
(POS/e-commerce platforms) commonly deliver from a shared pool of egress
IPs across many merchants and IP-keying would let one busy org exhaust
the bucket for an unrelated org. Default `60/minute`, configurable via
`WEBHOOK_RATE_LIMIT`.

## Rate limiting

`/api` routes (products, inventory, forecast — anything behind
`require_current_user`) are rate-limited via `slowapi`
(`app/core/rate_limit.py`), keyed by client IP. Default limit is
`100/minute`, configurable via the `RATE_LIMIT` env var. Limit exceeded
returns `429`. `/health` and `/metrics` are exempt.
`/api/webhooks/{organization_id}/ingest` has its own separate, per-org rate
limit instead (see "Webhook signature verification" above) — not exempt,
just a different `Limiter` instance with different keying.

Keying is by IP only, deliberately — not by the authenticated user. Partly
because `POST /api/auth/login` itself has no user identity to key on yet
(that's the whole point of rate-limiting it — see the auth section above),
and keying the rest by user would let an attacker reset their bucket on
every request just by using a different account, which doesn't actually
mitigate anything IP-based abuse (scraping, brute force) cares about.

**Known limitation:** the default `memory://` storage backend is
per-process, not shared across Gunicorn's worker processes in production
(`WEB_CONCURRENCY`, `deploy/docker-compose.prod.yml` — same gap
`PROMETHEUS_MULTIPROC_DIR` exists to solve for `/metrics`). The effective
limit in prod is therefore roughly `WEB_CONCURRENCY x RATE_LIMIT`, not
exactly `RATE_LIMIT`. Divide `RATE_LIMIT` by your worker count if you need
the exact ceiling; a shared backend (e.g. Redis) would fix this properly
but isn't in place yet.

**Resolved 2026-07-24 (#66):** rate limiting used to be enforced by
`slowapi`'s `SlowAPIMiddleware`, which finds each request's route handler by
scanning `app.routes` directly — ASGI middleware runs *before* routing, so
it has no other way to know which endpoint matched. FastAPI 0.140.0 changed
`include_router()` to wrap routes in a private `_IncludedRouter` object
instead of flattening them, which that scan doesn't recognize — the result
wasn't an error, rate limiting just silently stopped applying to every
`/api` route. Fixed by enforcing the limit via a FastAPI `Depends()`
(`enforce_rate_limit`, `app/core/rate_limit.py`) attached alongside the
auth dependency instead of a middleware — dependencies run *after*
routing has already resolved the endpoint, so there's no route-matching to
get wrong. `/health` and `/metrics` are exempt structurally now (the
dependency simply isn't attached to those routes) rather than via
slowapi's `@limiter.exempt` name-based lookup. `/api/webhooks/{organization_id}/ingest`
gets its own separate per-org-keyed dependency instead of this one — see
"Webhook signature verification" above.

**`rate_limit_key` now trusts a real client IP behind a proxy, instead of
always keying on the raw TCP peer.** Every documented deployment path puts
at most one reverse proxy in front of this app (Caddy over the Compose
network, or the ALB over its VPC), and in both cases the raw TCP peer
`request.client.host` sees is the proxy itself, not the real client — so
every real client behind the same proxy was sharing one rate-limit bucket.
`rate_limit_key` (`app/core/rate_limit.py`) now trusts `X-Forwarded-For`'s
leftmost entry, but **only** when the immediate TCP peer's address is
itself private (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`,
`127.0.0.0/8`) — i.e. only when the peer can only be our own proxy, never
an arbitrary internet client, who could otherwise forge the header to reset
their own bucket on every request. The one deployment path with no proxy at
all (`deploy/docker-compose.prod.yml` alone, plain HTTP on `:8000`) doesn't need
this: Docker's published-port NAT already preserves the real public client
IP as the TCP peer.

## Account lockout

`authenticate_user()` (`app/services/auth_service.py`) also enforces a
per-account lockout, independent of the IP-based rate limiting above: 5
consecutive failed attempts against one account locks it for 15 minutes
(`User.failed_login_attempts`/`locked_until`). This exists specifically
because it's the *only* brute-force protection on the dashboard's login
path (`dashboard/auth.py`'s `login_form()`, see "Dashboard access" below)
— that path calls `authenticate_user()` directly, in-process, with no HTTP
request/IP available to key an IP-based limit off of. Since both the API
and the dashboard share this one function, the API gets the same
protection as a second, redundant layer on top of its own IP rate limit.

A wrong attempt made right after a lockout expires still counts against
the same streak (the counter isn't proactively reset on expiry, only on an
actual successful login) — one grace attempt after the cooldown, not a
fresh set of 5. Locked-out and wrong-password responses are identical
(same generic `InvalidCredentialsError`, same audit-log distinction as
unknown-email vs. wrong-password) — a distinct "account locked" message
would itself leak that the account exists.

## Ingestion size limits

Both generic ingestion paths (see Epoch 7.2 in [`ROADMAP.md`](ROADMAP.md))
now cap the size of a single request, independent of the rate limits above:

- `POST /api/inventory/events/bulk` — any authenticated user can call this
  (it isn't admin-gated), and an unbounded CSV upload was read fully into
  memory before parsing. Capped at 10MB (rejected with `413` before pandas
  ever touches the body) and 50,000 rows (checked after parsing, catches a
  compact-but-huge-row-count file that's small in bytes).
- `POST /api/webhooks/{organization_id}/ingest` — has its own HMAC trust
  boundary and per-org rate limit (see "Webhook signature verification"
  above), plus `WebhookIngestPayload.events` capped at 1000 items per
  request — generous for a near-real-time delta, not a bulk history dump
  (that's what the CSV path above is for).

## Audit trail

`audit_log` (`app/models/audit_log.py`) records privilege-sensitive
actions — replay, export, role changes, login failures — via
`app/services/audit_service.py::log_action`, the only code path that
ever writes to the table, and it only ever inserts.

That was previously true only by *code convention*: the single shared
Postgres role the app connects as has full `UPDATE`/`DELETE` on every
table, `audit_log` included, so nothing at the database layer actually
enforced immutability. **Resolved (#99):** a Postgres trigger
(`audit_log_append_only`, added by the
`add audit log tamper protection trigger` migration) now rejects any
`UPDATE` or `DELETE` on `audit_log` outright, regardless of which role
issues it — a trigger rather than a `REVOKE` on today's app role
specifically, so the guarantee doesn't quietly stop applying if the app
ever moves off the current single-shared-role model. Inserts are
unaffected.

## Response security headers

Every response gets `X-Content-Type-Options: nosniff`, `X-Frame-Options:
DENY`, and `Referrer-Policy: no-referrer` (`app/core/security_headers.py`).
`Strict-Transport-Security` is added only when the request arrived over
HTTPS (detected via `X-Forwarded-Proto`, set by both Caddy and AWS's ALB) —
uvicorn itself always sees plain HTTP, since TLS is terminated upstream, so
asserting HSTS unconditionally would break local dev and the no-domain
plain-HTTP self-hosted path. Neither Caddy nor the ALB add these headers on
their own; `deploy/Caddyfile` is a bare `reverse_proxy`.

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
via the service layer — it doesn't go through `/api`, so it has none of
the bearer-token protection above, but it does have its own per-user
sign-in (`dashboard/auth.py`'s `login_form()`/`require_login()`), calling
`authenticate_user()` directly in-process rather than over HTTP. Same
accounts as the API (`scripts/create_user.py`), same generic-401-equivalent
"Invalid email or password" on failure, and — since it shares
`authenticate_user()` with the API — the same account lockout described
above.

**This "port never published by default" claim only holds for the
self-hosted production path.** There, its container port is never
published by default; it's only reachable once the Caddy overlay
(`deploy/docker-compose.caddy.yml`) also fronts it with HTTP basic auth on
a dedicated HTTPS listener (`https://<DOMAIN>:8501`) — see
[`docs/deployment/self-hosted.md`](docs/deployment/self-hosted.md). The
two don't replace each other there: basic auth is a network-perimeter
control (one shared username/password), the dashboard's own sign-in is
per-user identity inside the app.

The desktop/mobile path is different: the Tauri desktop wizard
(`tauri/src-tauri/src/docker.rs`) always runs the base
`deploy/docker-compose.yml` directly, which *does* publish `:8501`, and
has no Caddy overlay at all. Mobile (`tauri/src-mobile/config.js`) then
reaches that same port over Tailscale. So on this path, the account
lockout above — not Caddy's basic auth, not IP rate limiting — is the
dashboard login's only brute-force protection; the network-level gate is
Tailscale's own ACL (device/tailnet membership), not anything this app
controls.

## Prior security review

[`docs/archive/report.md`](docs/archive/report.md) is a point-in-time AI code
review from an earlier stage of the project. Most of its findings have since
been addressed (see the commit history around `feat(auth)`), but it's kept as
project history rather than updated in place — it's not a live status report.
