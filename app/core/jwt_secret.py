# app/core/jwt_secret.py
#
# The one place that decides what JWT_SECRET is. It signs login tokens
# (app/core/auth.py) and the Square OAuth `state` (app/services/square_service.py);
# both used to re-implement the fallback separately, and the startup warning in
# app/main.py used a third, different test of "is it set?" -- which disagreed
# with them for an empty value (#385). Everything now asks this module.

import os

# Public: it's in the source and the docs. Anyone can sign a valid token or
# OAuth state with it, which is why a deployment reachable by anyone you
# don't trust must set a real JWT_SECRET (see SECURITY.md).
DEV_JWT_SECRET = "insecure-dev-secret-do-not-use-in-production"  # noqa: S105 -- public dev default


def get_jwt_secret() -> str:
    """The configured secret, or the public dev default if it's unset or blank.

    "Blank" includes an empty string and whitespace only: `JWT_SECRET=` (as
    shipped in .env.example) arrives as "", not as a missing variable. A real
    secret is returned exactly as given -- not stripped -- so existing tokens
    keep verifying.
    """
    value = os.getenv("JWT_SECRET")
    if value is None or not value.strip():
        return DEV_JWT_SECRET
    return value


def is_dev_jwt_secret() -> bool:
    """True when the app would sign with the public dev default."""
    return get_jwt_secret() == DEV_JWT_SECRET
