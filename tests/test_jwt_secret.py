# tests/test_jwt_secret.py
#
# #385: an empty JWT_SECRET ("JWT_SECRET=" as shipped in .env.example) used to
# fall back to the public dev secret with NO startup warning, because the
# fallback treated "" as missing (`or`) but the warning only checked `is None`.

import logging
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEV_SECRET = "insecure-dev-secret-do-not-use-in-production"  # noqa: S105 -- public dev default


@pytest.mark.parametrize("raw", [None, "", "   ", "\t\n"])
def test_missing_or_blank_secret_is_the_dev_default(monkeypatch, raw):
    from app.core.jwt_secret import DEV_JWT_SECRET, get_jwt_secret, is_dev_jwt_secret

    if raw is None:
        monkeypatch.delenv("JWT_SECRET", raising=False)
    else:
        monkeypatch.setenv("JWT_SECRET", raw)

    assert DEV_JWT_SECRET == _DEV_SECRET
    assert get_jwt_secret() == _DEV_SECRET
    assert is_dev_jwt_secret() is True


def test_real_secret_is_returned_untouched(monkeypatch):
    from app.core.jwt_secret import get_jwt_secret, is_dev_jwt_secret

    # Not stripped: a real secret must keep its exact bytes, or every token
    # signed before this change would stop verifying.
    monkeypatch.setenv("JWT_SECRET", "  padded-real-secret  ")

    assert get_jwt_secret() == "  padded-real-secret  "
    assert is_dev_jwt_secret() is False


def _startup_warnings(monkeypatch, caplog, value):
    from app.main import app

    if value is None:
        monkeypatch.delenv("JWT_SECRET", raising=False)
    else:
        monkeypatch.setenv("JWT_SECRET", value)

    with caplog.at_level(logging.WARNING, logger="ims"):
        with TestClient(app):  # entering the context runs the lifespan startup
            pass
    return [r for r in caplog.records if "JWT_SECRET" in r.getMessage()]


@pytest.mark.parametrize("value", [None, "", "   "])
def test_startup_warns_when_secret_is_unset_or_blank(monkeypatch, caplog, value):
    # The "" case is the bug: it used to log nothing.
    assert _startup_warnings(monkeypatch, caplog, value), (
        f"no JWT_SECRET startup warning for JWT_SECRET={value!r}"
    )


def test_startup_does_not_warn_with_a_real_secret(monkeypatch, caplog):
    assert not _startup_warnings(monkeypatch, caplog, "a-real-random-secret-9f3b2c71")


@pytest.mark.parametrize(
    "env_value, expected",
    [
        (None, _DEV_SECRET),
        ("", _DEV_SECRET),
        ("   ", _DEV_SECRET),
        ("a-real-random-secret-9f3b2c71", "a-real-random-secret-9f3b2c71"),
    ],
)
def test_token_signing_and_oauth_state_use_the_same_secret(env_value, expected):
    # Fresh interpreter on purpose: both modules read the secret at import
    # time, and reloading them in-process would desync the already-built app.
    # They used to each re-implement the fallback; they must now agree.
    code = (
        "import os; "
        "from app.core import auth; from app.services import square_service; "
        "print(auth._JWT_SECRET); print(square_service._STATE_SECRET)"
    )
    env = {k: v for k, v in __import__("os").environ.items() if k != "JWT_SECRET"}
    if env_value is not None:
        env["JWT_SECRET"] = env_value
    out = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, "-c", code],
        cwd=_REPO_ROOT,
        env={**env, "PYTHONPATH": str(_REPO_ROOT)},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert out == [expected, expected]


class _ComposeLoader(yaml.SafeLoader):
    """SafeLoader that tolerates compose-only tags such as `!override`."""


def _construct_tagged(loader, tag_suffix, node):
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_scalar(node)


_ComposeLoader.add_multi_constructor("!", _construct_tagged)


@pytest.mark.parametrize("service", ["api", "dashboard"])
def test_prod_compose_refuses_to_start_without_a_jwt_secret(service):
    # Same `:?` guard as POSTGRES_PASSWORD: compose aborts if the variable is
    # unset OR empty, so a copied-but-unfilled .env.example can't reach prod.
    text = (_REPO_ROOT / "deploy" / "docker-compose.prod.yml").read_text()
    compose = yaml.load(text, Loader=_ComposeLoader)  # noqa: S506 -- a SafeLoader subclass
    value = compose["services"][service]["environment"]["JWT_SECRET"]
    assert value.startswith("${JWT_SECRET:?"), value
