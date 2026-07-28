# Model Registry (MLflow)

`make train` logs every Prophet training run to a local MLflow model
registry — training metrics, model params, and the model artifact itself,
versioned per product (registered model name: `prophet_{product_id}`).

This is separate from model *serving*: the API still loads
`models/prophet_{product_id}.pkl` directly (see `forecast_service.load_model`),
unchanged. The registry is a record of what was trained, when, and how it
scored — useful for comparing runs and knowing what to roll back to; it
doesn't sit in the request path.

## Setup

Training dependencies aren't part of `requirements.txt` (and therefore not
part of the API Docker image) — they're only needed on whatever machine
runs `make train`:

```bash
make train-deps   # pip install -r requirements-train.txt
make train
```

By default the registry is backed by a local SQLite file at `mlflow.db`
(repo root), with artifacts under `mlruns/`. Both are gitignored — override
with `MLFLOW_TRACKING_URI` / `MLFLOW_EXPERIMENT_NAME` env vars if you want a
shared registry (e.g. a `postgresql://` URI) instead.

MLflow's plain filesystem tracking store (`file:./mlruns` with no database)
is in maintenance mode and doesn't support the model registry — that's why
SQLite is the default here, not a bare directory.

## Viewing runs

`mlflow-skinny` (what `requirements-train.txt` installs) is the tracking/registry
client only — it doesn't bundle the web UI. Two options:

**Python client** (works with `mlflow-skinny`, no extra install):

```python
import mlflow
mlflow.set_tracking_uri("sqlite:///mlflow.db")
client = mlflow.MlflowClient()
for v in client.search_model_versions("name='prophet_1'"):
    print(v.version, v.aliases, v.creation_timestamp)
```

**Web UI** (needs the full `mlflow` package, not `mlflow-skinny`):

```bash
pip install mlflow
mlflow ui --backend-store-uri sqlite:///mlflow.db
```

Then open `http://localhost:5000`.

## Promotion and rollback

MLflow's model *stages* API (Staging/Production) is deprecated in favor of
**aliases** — arbitrary named pointers to a specific version. This project
uses `champion` as the alias for "the version currently being served."

**Promotion is automatic, not a review gate.** Every `make train` run
immediately overwrites `models/prophet_{product_id}.pkl` (what
`forecast_service.load_model()` reads) and now also moves `champion` to
match, via `forecast_service._log_run_to_mlflow()` — the alias just makes
the registry tell the truth about what's live; it was never a gate a human
had to approve before this, and adding one here would silently break
automated retraining's whole point (see the "Automated retraining" section
below).

**Rolling back what's actually serving:**

```bash
python -m app.scripts.rollback_model --product-id 1 --version 2
```

This is `forecast_service.rollback_model()` — loads that version's artifact
from the registry, overwrites `models/prophet_{product_id}.pkl` with it
(the same S3-aware `storage` write path `train_model()` uses, so this works
whether `MODELS_DIR` is local disk or S3/MinIO), and re-points `champion` at
that version so the registry stays consistent with what's live. Find the
version to roll back to via the Python client or web UI shown above
(`client.search_model_versions("name='prophet_1'")`).

## Automated retraining

`scripts/retrain_cron.sh` wraps `make features && make train` for
unattended, scheduled retraining — see its own header comment and
`docs/deployment/self-hosted.md`'s "Automated retraining" section for the
crontab line. There is no promotion review step: a cron-triggered retrain
goes live immediately, same as a manually-run `make train` always has.
If a bad retrain ever needs undoing, `rollback_model` above is the fix, not
a pre-emptive approval gate on every run.
