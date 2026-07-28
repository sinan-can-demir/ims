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

## Temporary public demo (no domain, no Cloudflare account needed)

If you just want to show someone the dashboard live over the internet —
not a real deployment, no domain, no signup of any kind — use Cloudflare's
**quick tunnel**. It gives you a real public HTTPS URL pointed at whatever's
running locally, for free, with zero account.

```bash
# One-time install
curl -fsSL -o ~/.local/bin/cloudflared \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x ~/.local/bin/cloudflared
```

The dashboard isn't published to the host at all under `docker-compose.prod.yml`
without the Caddy overlay (see above), so the tunnel has nothing to point at
until you temporarily publish it to localhost:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  -f - up -d dashboard <<'EOF'
services:
  dashboard:
    ports:
      - "127.0.0.1:8501:8501"
EOF
```

Then start the tunnel:

```bash
~/.local/bin/cloudflared tunnel --url http://localhost:8501
```

It prints a URL like `https://some-random-words.trycloudflare.com` within
a few seconds — that's a real, publicly reachable HTTPS address serving the
live dashboard, from anywhere. Anyone with the link can open it; the
dashboard's own per-user login is the only thing gating actual access.

**This is not a permanent deployment**, by design:
- The URL only exists as long as that `cloudflared` process keeps running.
  Close the terminal, sleep the laptop, or lose network, and it's gone.
- Restarting `cloudflared` (crash, reconnect after a long outage, etc.)
  generates a **new random URL** — the old one doesn't come back.
- Cloudflare's own banner is explicit: account-less tunnels have no uptime
  guarantee and aren't for production use.

When you're done, `Ctrl+C` the tunnel and revert the port publish:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d dashboard
```

**Why not a stable custom domain instead?** A permanent address needs a
Cloudflare *named* tunnel, and as of 2026-07 both ways to create one are
blocked without either a payment method or a domain you already own:
the Zero Trust dashboard flow requires a card on file even for its "$0/month"
free plan (to authorize potential overage), and the classic CLI flow
(`cloudflared tunnel login`) requires selecting an existing zone in your
Cloudflare account — a free subdomain like [is-a.dev](https://is-a.dev/)
can't fill that slot, since its zone belongs to that project, not you.
So a real stable public URL for this deployment still needs either a paid
domain or an actual reachable host (see `#74` in ROADMAP.md).

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
