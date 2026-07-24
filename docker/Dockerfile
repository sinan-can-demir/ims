# Pinned by digest (not just the "3.11-slim" tag) for reproducibility and
# supply-chain integrity — the tag is mutable and could be repointed upstream.
# This is a manifest-list digest, so the correct platform (amd64/arm64) is
# still resolved at pull time. Re-resolve periodically with:
#   skopeo inspect docker://docker.io/library/python:3.11-slim
ARG PYTHON_BASE_IMAGE=python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93

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
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY . .

ENV PYTHONPATH=/app

# UID 1000 matches the default first-user UID on most Linux distros
# (including Fedora), so the dev bind-mount in docker-compose.yml stays
# writable without needing a matching --user override.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Plain single-worker Uvicorn by default — matches what docker-compose.yml's
# dev command and docker-compose.prod.yml/infra/ecs.tf's production commands
# all explicitly override anyway. Production paths run Gunicorn with
# UvicornWorker instead (see docker-compose.prod.yml, infra/ecs.tf); this is
# just a sane default for anyone running the image directly.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
