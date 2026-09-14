# Pinned by digest (not just the "3.11-slim" tag) for reproducibility and
# supply-chain integrity — the tag is mutable and could be repointed upstream.
# This is a manifest-list digest, so the correct platform (amd64/arm64) is
# still resolved at pull time. Re-resolve periodically with:
#   skopeo inspect docker://docker.io/library/python:3.11-slim
ARG PYTHON_BASE_IMAGE=python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534

# ---- builder: install deps into an isolated venv, nothing else survives ----
FROM ${PYTHON_BASE_IMAGE} AS builder

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# venv bootstraps with whatever pip/setuptools/wheel shipped in the base
# image, which can lag behind fixed CVEs in setuptools' vendored deps
# (e.g. jaraco.context, wheel itself) — upgrade before installing anything.
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- final: runtime image only, no pip cache / apt lists / build layer ----
FROM ${PYTHON_BASE_IMAGE}

WORKDIR /app

# curl is needed by the HEALTHCHECK below; not present in the slim base image.
#
# --only-upgrade closes CVEs where the pinned base image's own packages lag
# Debian's security repo (confirmed via `apt-cache policy` against this
# exact base image) because the upstream python:3.11-slim image hasn't been
# rebuilt with them yet. Re-pinning PYTHON_BASE_IMAGE's digest (the usual
# fix for a base-image CVE, see that ARG's comment) doesn't help here — no
# newer digest exists yet to re-pin to:
#   - openssl/openssl-provider-legacy (pulls the matching libssl3t64 in as
#     a dependency): CVE-2026-14456
#   - perl-base: CVE-2026-13221 (CRITICAL) plus the perl-Archive-Tar/
#     perl-IO-Compress/Storable CVEs bundled into the same package
#   - gzip: CVE-2026-41992
#   - libpcre2-8-0: CVE-2026-86145, CVE-2026-89161
#   - libsqlite3-0: CVE-2026-11822, CVE-2026-11824
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && apt-get install -y --no-install-recommends --only-upgrade \
        openssl openssl-provider-legacy \
        perl-base gzip libpcre2-8-0 libsqlite3-0 \
    && rm -rf /var/lib/apt/lists/*

# This stage is FROM the base image directly (not the builder), so it still
# carries the base image's own system-wide setuptools, unaffected by the
# builder's venv-scoped upgrade above — runtime never imports it (the app
# runs out of /opt/venv only), but it's still present in the image and
# scanned. Upgrade it here too to close CVE-2025-47273 (path traversal in
# setuptools' PackageIndex).
RUN pip install --no-cache-dir --upgrade setuptools

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# pip itself is never invoked at runtime (verified: no `pip install` /
# subprocess call anywhere in app/dashboard/scripts -- installing deps is a
# build-time-only concern already done above). Removing it also removes its
# statically bundled `pip/_vendor` copies of msgpack and setuptools, which
# ship real CVEs (GHSA-6v7p-g79w-8964, CVE-2025-47273) fixed upstream in
# those projects but frozen at pip's own vendored versions until pip cuts a
# new release -- neither a `requirements.txt` bump nor a base-image re-pin
# touches pip's internal vendor bundle.
RUN rm -rf /opt/venv/lib/python3.11/site-packages/pip \
        /opt/venv/lib/python3.11/site-packages/pip-*.dist-info \
        /opt/venv/bin/pip /opt/venv/bin/pip3 /opt/venv/bin/pip3.11 \
        /usr/local/lib/python3.11/site-packages/pip \
        /usr/local/lib/python3.11/site-packages/pip-*.dist-info \
        /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.11

COPY . .

ENV PYTHONPATH=/app

# UID 1000 matches the default first-user UID on most Linux distros
# (including Fedora), so the dev bind-mount in deploy/docker-compose.yml stays
# writable without needing a matching --user override.
#
# The 4 `mkdir -p` targets must exist here with correct ownership
# regardless of whether the build context happens to have content in them
# (data_lake/feature_store are gitignored and may be genuinely empty on a
# fresh clone) — deploy/docker-compose.prod.yml mounts named volumes at these
# exact paths, and Docker only copies the image's existing ownership into
# a fresh named volume on first mount if the directory already exists in
# the image. Without this, an empty/absent dir gets created root-owned,
# and appuser's own `Path.mkdir()` calls at runtime fail with EACCES.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p data_lake warehouse feature_store models \
    && chown -R appuser:appuser /app
USER appuser

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Plain single-worker Uvicorn by default — matches what deploy/docker-compose.yml's
# dev command and deploy/docker-compose.prod.yml/infra/ecs.tf's production commands
# all explicitly override anyway. Production paths run Gunicorn with
# UvicornWorker instead (see deploy/docker-compose.prod.yml, infra/ecs.tf); this is
# just a sane default for anyone running the image directly.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
