# app/scripts/train_model.py
#
# Trains models for every active organization by default — same reason
# as app/scripts/build_features.py's header comment (train_all_models()
# is org-scoped, and scripts/retrain_cron.sh needs this to loop
# automatically so a newly created org gets scheduled retraining without
# any cron reconfiguration — see #171). Pass --organization-id to target
# just one org instead, same shape as rollback_model.py's flag.

import argparse

from app.database import SessionLocal
from app.models.organization import Organization
from app.services.forecast_service import train_all_models


def _active_organization_ids() -> list[int]:
    db = SessionLocal()
    try:
        return [
            org.id
            for org in db.query(Organization)
            .filter(Organization.is_active.is_(True))
            .order_by(Organization.id)
            .all()
        ]
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Train demand-forecasting models.")
    parser.add_argument(
        "--organization-id",
        type=int,
        default=None,
        help="Train only this org's models. Default: every active organization.",
    )
    args = parser.parse_args()

    org_ids = (
        [args.organization_id] if args.organization_id is not None else _active_organization_ids()
    )

    for org_id in org_ids:
        results = train_all_models(org_id)
        for r in results:
            print(r)

    print("All models trained")


if __name__ == "__main__":
    main()
