# Self-Hosted Deployment

The recommended way to run IMS for real use — no cloud account, no vendor
lock-in, ~$5-20/month on any VPS. Built entirely on the Docker Compose setup
already used for local development, plus [Caddy](https://caddyserver.com/)
(open-source, automatic HTTPS) if you have a domain.

Looking for an AWS/enterprise deployment instead? See
[`infra/README.md`](../../infra/README.md).

## Prerequisites

- A VPS with Docker + the Compose plugin installed. Any provider works —
  Hetzner, DigitalOcean, OVH, a spare machine at home, etc. A 1-2 vCPU /
  2-4GB RAM box is plenty to start.
- (Optional) A domain name, if you want HTTPS via Caddy. Not required —
  you can run over plain HTTP first and add this later.

## 1. Get Docker onto the server

Most providers offer a "Docker" marketplace image that comes with this
preinstalled. Otherwise, on a fresh Debian/Ubuntu box:

```bash
curl -fsSL https://get.docker.com | sh
```

## 2. Clone the repo and configure

```bash
git clone https://github.com/sinan-can-demir/ims-manual.git
cd ims-manual
cp .env.example .env
```

Edit `.env` and set, at minimum:
- `POSTGRES_PASSWORD` — a real password (the compose config refuses to
  start without one; there's no insecure default in production mode)
- `JWT_SECRET` — generate with `openssl rand -hex 32`. Leaving this unset
  falls back to a fixed, publicly-known dev secret rather than disabling
  auth (there's no way to "disable" JWT signing) — fine for local dev but
  **not** for anything reachable on the open internet — see
  [`SECURITY.md`](../../SECURITY.md).
- `CORS_ORIGINS` — if you're also running the dashboard, point this at
  wherever it's served from.

## 3. Start the stack

**Without a domain (plain HTTP):**

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

The API is now reachable at `http://<server-ip>:8000`.

**With a domain (automatic HTTPS via Caddy):**

Point an A record for your domain at the server's public IP first, then also
set `DOMAIN=your-domain.com` in `.env`:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.caddy.yml up -d --build
```

Caddy requests and renews a Let's Encrypt certificate automatically — no
manual cert management. The API is now reachable at `https://your-domain.com`.

In both modes, `docker-compose.prod.yml` also: runs the built image only (no
live source bind-mount), restarts containers automatically on crash/reboot
(`restart: unless-stopped`), and stops publishing Postgres's port to the
outside world — only the `api` container can reach it, over the internal
Docker network.

## 4. Verify

There's no self-service registration — create your first account with
`scripts/create_user.py` (inside the `api` container, or anywhere with
`DATABASE_URL` pointed at the same Postgres):

```bash
docker compose exec api python scripts/create_user.py --email you@example.com --display-name "Your Name"
```

```bash
curl http://<server-ip>:8000/health          # or https://your-domain.com/health
TOKEN=$(curl -s -X POST http://<server-ip>:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"<your password>"}' | jq -r .access_token)
curl -H "Authorization: Bearer $TOKEN" http://<server-ip>:8000/api/products
```

## Updating

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml [-f docker-compose.caddy.yml] up -d --build
```

Migrations run automatically on container start (same `alembic upgrade head`
step as local dev).

## Dashboard (optional, requires a domain)

The Streamlit dashboard runs as part of the stack (`dashboard` service) and
now has its own per-user sign-in (`dashboard/auth.py`) — same accounts as
the API, created the same way via `scripts/create_user.py` (see
[step 4 above](#4-verify)). Its container port is still never published directly, though;
it's only reachable once the Caddy overlay fronts it with HTTP basic auth
on its own HTTPS listener — a separate, network-perimeter layer on top of
the per-user sign-in, not a replacement for it. Running
`docker-compose.prod.yml` without the Caddy overlay leaves the dashboard
**unreachable**, not merely unauthenticated.

To enable it, in addition to `DOMAIN`, set in `.env`:

```bash
DASHBOARD_AUTH_USER=<pick a username>
DASHBOARD_AUTH_HASH=<generate below>
```

Generate the password hash (Caddy stores bcrypt hashes, never plaintext).
Pipe it through `sed` to double each `$` — bcrypt hashes contain literal `$`
characters, and without this, Compose's `.env` interpolation treats
`$word` as a variable reference and silently truncates the hash:

```bash
docker run --rm caddy:2-alpine caddy hash-password --plaintext '<your password>' | sed 's/\$/$$/g'
```

Then bring up the stack with the Caddy overlay as usual:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.caddy.yml up -d --build
```

The dashboard is now reachable at `https://your-domain.com:8501`, prompting
for the username/password above. Make sure port `8501` is open in your
server's firewall alongside `80`/`443`.

## Backups

`scripts/backup.sh <destination_dir>` backs up the Postgres database
*and* the local pipeline artifacts (data_lake, feature_store, warehouse,
models) into one timestamped archive — the pipeline half of this used to
be undocumented (see "What this doesn't cover" below, now resolved):

```bash
scripts/backup.sh /path/to/backup/dir
# writes /path/to/backup/dir/ims-backup-<UTC timestamp>.tar.gz
```

This only writes locally — point `<destination_dir>` at a mounted network
drive or synced folder, or wrap the call in your own `rsync`, for real
off-server durability. A cron job calling `scripts/backup.sh` on whatever
schedule matters to you is enough for most self-hosted use.

To restore (destructive — replaces the current database and pipeline
artifacts, prompts for confirmation):

```bash
scripts/restore.sh /path/to/backup/dir/ims-backup-<timestamp>.tar.gz
```

Both require the `db` service to be up (`docker compose up -d db`).
