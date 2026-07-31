# app/scripts/train_model.py
#
# Trains org 1's models only — same known gap as
# app/scripts/build_features.py's header comment describes, for the
# same reason (train_all_models() is org-scoped, this CLI doesn't loop
# over every active org yet).

from app.services.forecast_service import train_all_models


def main() -> None:
    results = train_all_models()
    for r in results:
        print(r)

    print("All models trained")


if __name__ == "__main__":
    main()
