# app/scripts/rollback_model.py
#
# Roll a product's live-serving model back to a specific prior MLflow
# registry version — see forecast_service.rollback_model() and
# docs/model-registry.md.
#
# Usage:
#   python -m app.scripts.rollback_model --product-id 1 --version 2

import argparse

from app.services.forecast_service import rollback_model


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Roll back a product's live-serving forecast model to a prior version."
    )
    parser.add_argument("--product-id", type=int, required=True)
    parser.add_argument("--version", type=int, required=True)
    args = parser.parse_args()

    try:
        result = rollback_model(args.product_id, args.version)
    except (ValueError, FileNotFoundError) as exc:
        print(f"✗ {exc}")
        raise SystemExit(1) from exc

    print(f"✓ product {result['product_id']} now serving version {result['version']}")


if __name__ == "__main__":
    main()
