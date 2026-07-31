# app/scripts/build_features.py
#
# Builds org 1's feature store only — build_features() is org-scoped
# (Epoch 10 PR 15, #151) but this CLI/`make features` doesn't loop over
# every active org yet, unlike app/scripts/rollback_model.py which does
# take an --organization-id flag. Fine for the default single-org
# self-hosted deployment; a real multi-org deployment relying on this
# for scheduled retraining (see scripts/retrain_cron.sh) would currently
# only ever build/refresh org 1's features. Flagged as a known gap, not
# addressed here.

from app.services.feature_service import build_features


def main() -> None:
    rows = build_features()
    print(f"Feature store built: {rows} rows written")


if __name__ == "__main__":
    main()
