# app/scripts/build_features.py
#
# Builds the feature store for every active organization by default —
# build_features() is org-scoped (Epoch 10 PR 15, #151), and
# scripts/retrain_cron.sh's unattended cron job relies on this looping
# automatically so a newly created org gets scheduled retraining without
# any cron reconfiguration (see #171). Pass --organization-id to target
# just one org instead, same shape as rollback_model.py's flag.

import argparse

from app.database import SessionLocal
from app.models.organization import Organization
from app.services.feature_service import build_features


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
    parser = argparse.ArgumentParser(description="Build the feature store.")
    parser.add_argument(
        "--organization-id",
        type=int,
        default=None,
        help="Build only this org's features. Default: every active organization.",
    )
    args = parser.parse_args()

    org_ids = (
        [args.organization_id] if args.organization_id is not None else _active_organization_ids()
    )

    for org_id in org_ids:
        rows = build_features(org_id)
        print(f"Feature store built for org {org_id}: {rows} rows written")


if __name__ == "__main__":
    main()
