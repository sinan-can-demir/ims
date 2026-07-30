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
git clone https://github.com/sinan-can-demir/ims.git
cd ims
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
- `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` — MinIO (the self-hosted
  S3-compatible object storage backend, see below) runs by default
  alongside the rest of the stack and refuses to start without these,
  same as `POSTGRES_PASSWORD`. You don't have to actually *use* it —
  local disk stays the default for the data pipeline either way — but
  it needs valid credentials to boot regardless.

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
(`restart: unless-stopped`), stops publishing Postgres's port to the outside
world — only the `api` container can reach it, over the internal Docker
network — and starts a `minio` container the same way (see
[S3 / MinIO storage](#s3--minio-storage-optional) below). The data pipeline
doesn't actually route through MinIO by default — local disk stays its
default storage regardless — `minio` just runs alongside everything else,
ready if you turn it on.

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

## S3 / MinIO storage (optional)

The data pipeline (`data_lake/`, `warehouse/`, `feature_store/`, `models/`)
defaults to local disk — the named volumes from step 3 already make that
durable across redeploys. MinIO (an open-source S3-compatible object store)
runs alongside the rest of the stack by default too, but nothing routes
through it until you point the relevant paths at it.

To actually use it, set these in `.env` (in addition to
`MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` from step 2):

```bash
S3_ENDPOINT_URL=http://minio:9000
AWS_ACCESS_KEY_ID=<same as MINIO_ROOT_USER>
AWS_SECRET_ACCESS_KEY=<same as MINIO_ROOT_PASSWORD>
S3_URL_STYLE=path
```

Then point whichever of the 4 pipeline paths you want on S3 at a bucket URI,
e.g.:

```bash
DATA_LAKE_ROOT=s3://ims/data_lake
WAREHOUSE_ROOT=s3://ims/warehouse
FEATURE_STORE_PATH=s3://ims/feature_store
MODELS_DIR=s3://ims/models
```

Create the bucket first — `docker compose exec minio mc alias set local
http://localhost:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD && docker compose
exec minio mc mb local/ims` — then recreate the stack (`docker compose -f
docker-compose.yml -f docker-compose.prod.yml up -d --build`) to pick up the
new `.env` values.

One path stays local no matter what: `WAREHOUSE_DB_PATH` (the DuckDB catalog
file dbt and the feature-builder both open) — there's no supported way to
run a writable DuckDB database directly on S3, so it's always a local file,
rebuilt from S3-hosted source parquet on each `dbt run` when `WAREHOUSE_ROOT`
itself is on S3. Don't set it to an `s3://` URI.

`scripts/backup.sh`/`scripts/restore.sh` only ever cover local disk — they
print an explicit warning naming which paths they're skipping if any are on
S3. For S3/MinIO durability instead, use bucket versioning (`docker compose
exec minio mc version enable local/ims`) and back up the `minio_data` Docker
volume itself on whatever schedule matters to you, the same way you would
any other named volume.

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

## Automated retraining

`make train` (Prophet demand forecasting) is a hand-run command by
default. `scripts/retrain_cron.sh` wraps `make features && make train` for
unattended, scheduled retraining via a plain host cron entry:

```bash
# Daily at 3am, output appended to a log file:
0 3 * * * cd /path/to/ims && scripts/retrain_cron.sh >> /var/log/ims-retrain.log 2>&1
```

Requires training dependencies installed on the host (`make train-deps`)
and a real Postgres reachable at `DATABASE_URL`, same as running
`make train` by hand. Every run immediately replaces every product's
live-serving model — there's no review gate (see
[`docs/model-registry.md`](../model-registry.md#automated-retraining)).
If a bad retrain needs undoing:

```bash
python -m app.scripts.rollback_model --product-id 1 --version 2
```

## Automated data export

`make export` (`python -m app.scripts.export_events`) exports inventory
events to the Parquet data lake, incrementally — only events since the
last checkpoint, across every org in one run (see
`app/services/export_service.py` — the checkpoint is deliberately global,
not per-org). This used to also be reachable from the per-org admin
dashboard; that button was removed in Epoch 10 PR 13 (#149), since a
single org's admin triggering a whole-deployment operation was never the
right shape once real multi-tenancy existed. It's ops-only now, same
precedent as retraining above — a plain host cron entry:

```bash
# Every 15 minutes, output appended to a log file:
*/15 * * * * cd /path/to/ims && make export >> /var/log/ims-export.log 2>&1
```

Requires a real Postgres reachable at `DATABASE_URL`, same as running
`make export` by hand. Exported files land under
`org_id={id}/year=.../month=.../day=...` — org is the outermost
partition level, so an org-specific export/analytics job can point at
just its own subtree without reading the whole data lake.
