# tests/test_square_service.py
#
# ROADMAP.md's "Food Cost Visibility" Phase 3. Real (network-independent)
# logic tested directly: state signing/verification, connection status,
# token-refresh scheduling, DB read/write. exchange_code_for_token()/
# refresh_access_token() are the two functions that call the real Square
# API -- mocked here (no Square Application Secret available yet to test
# against the real endpoint), same convention this repo already uses for
# other external calls (see tests/test_dashboard.py's _mock_forecast).

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.organization import Organization
from app.services import square_service


def test_make_state_then_verify_state_round_trips(monkeypatch):
    monkeypatch.setattr(square_service, "_STATE_SECRET", "test-secret")
    state = square_service.make_state(organization_id=1)
    assert square_service.verify_state(state) == 1


def test_verify_state_rejects_tampered_signature(monkeypatch):
    monkeypatch.setattr(square_service, "_STATE_SECRET", "test-secret")
    state = square_service.make_state(organization_id=1)
    tampered = state[:-1] + ("0" if state[-1] != "0" else "1")

    with pytest.raises(square_service.SquareOAuthError):
        square_service.verify_state(tampered)


def test_verify_state_rejects_state_signed_with_a_different_secret(monkeypatch):
    monkeypatch.setattr(square_service, "_STATE_SECRET", "secret-a")
    state = square_service.make_state(organization_id=1)

    monkeypatch.setattr(square_service, "_STATE_SECRET", "secret-b")
    with pytest.raises(square_service.SquareOAuthError):
        square_service.verify_state(state)


def test_verify_state_rejects_expired_state(monkeypatch):
    monkeypatch.setattr(square_service, "_STATE_SECRET", "test-secret")
    monkeypatch.setattr(square_service, "_STATE_MAX_AGE_SECONDS", 1)

    old_state = square_service._sign_state(organization_id=1, timestamp=int(time.time()) - 5)
    with pytest.raises(square_service.SquareOAuthError):
        square_service.verify_state(old_state)


def test_verify_state_rejects_malformed_state(monkeypatch):
    monkeypatch.setattr(square_service, "_STATE_SECRET", "test-secret")
    with pytest.raises(square_service.SquareOAuthError):
        square_service.verify_state("not-a-real-state")


def test_get_authorize_url_requires_application_id(monkeypatch):
    monkeypatch.setattr(square_service, "SQUARE_APPLICATION_ID", None)
    with pytest.raises(square_service.SquareOAuthError):
        square_service.get_authorize_url(organization_id=1, redirect_uri="https://example.com/cb")


def test_get_authorize_url_includes_state_and_read_only_scope(monkeypatch):
    monkeypatch.setattr(square_service, "SQUARE_APPLICATION_ID", "sandbox-sq0idb-test")
    monkeypatch.setattr(square_service, "_STATE_SECRET", "test-secret")

    url = square_service.get_authorize_url(organization_id=1, redirect_uri="https://example.com/cb")

    assert "client_id=sandbox-sq0idb-test" in url
    assert "ORDERS_READ" in url
    # Read-only connector -- must never request a write scope.
    assert "ORDERS_WRITE" not in url
    assert "redirect_uri=https://example.com/cb" in url

    state = url.split("state=")[1].split("&")[0]
    assert square_service.verify_state(state) == 1


@patch("app.services.square_service.httpx.post")
def test_exchange_code_for_token_calls_square_with_the_right_shape(mock_post, monkeypatch):
    monkeypatch.setattr(square_service, "SQUARE_APPLICATION_ID", "sandbox-sq0idb-test")
    monkeypatch.setattr(square_service, "SQUARE_APPLICATION_SECRET", "sandbox-sq0csb-test")
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "access_token": "EAAA-fake-token",
        "refresh_token": "EQAA-fake-refresh",
        "merchant_id": "M-fake",
        "expires_at": "2026-10-05T00:00:00Z",
    }

    result = square_service.exchange_code_for_token("auth-code-123", "https://example.com/cb")

    assert result["access_token"] == "EAAA-fake-token"  # noqa: S105 -- fake test value, not a real credential
    call_kwargs = mock_post.call_args.kwargs
    assert call_kwargs["json"]["client_id"] == "sandbox-sq0idb-test"
    assert call_kwargs["json"]["client_secret"] == "sandbox-sq0csb-test"  # noqa: S105 -- fake test value
    assert call_kwargs["json"]["code"] == "auth-code-123"
    assert call_kwargs["json"]["grant_type"] == "authorization_code"


@patch("app.services.square_service.httpx.post")
def test_exchange_code_for_token_raises_on_non_200(mock_post, monkeypatch):
    monkeypatch.setattr(square_service, "SQUARE_APPLICATION_ID", "sandbox-sq0idb-test")
    monkeypatch.setattr(square_service, "SQUARE_APPLICATION_SECRET", "sandbox-sq0csb-test")
    mock_post.return_value.status_code = 401
    mock_post.return_value.text = "invalid_grant"

    with pytest.raises(square_service.SquareOAuthError):
        square_service.exchange_code_for_token("bad-code", "https://example.com/cb")


def test_save_connection_persists_tokens_on_the_organization(db):
    token_response = {
        "access_token": "EAAA-fake-token",
        "refresh_token": "EQAA-fake-refresh",
        "merchant_id": "M-fake",
        "expires_at": "2026-10-05T00:00:00+00:00",
    }

    org = square_service.save_connection(db, organization_id=1, token_response=token_response)

    assert org.square_access_token == "EAAA-fake-token"  # noqa: S105 -- fake test value
    assert org.square_refresh_token == "EQAA-fake-refresh"  # noqa: S105 -- fake test value
    assert org.square_merchant_id == "M-fake"
    assert square_service.is_connected(org)


def test_disconnect_clears_all_square_fields(db):
    square_service.save_connection(
        db,
        organization_id=1,
        token_response={
            "access_token": "EAAA-fake-token",
            "refresh_token": "EQAA-fake-refresh",
            "merchant_id": "M-fake",
            "expires_at": "2026-10-05T00:00:00+00:00",
        },
    )

    square_service.disconnect(db, organization_id=1)

    org = db.query(Organization).filter(Organization.id == 1).first()
    assert not square_service.is_connected(org)
    assert org.square_refresh_token is None
    assert org.square_merchant_id is None
    assert org.square_token_expires_at is None


def test_needs_token_refresh_false_when_not_connected():
    org = Organization(id=1, name="Test", webhook_secret="x")  # noqa: S106 -- fake test value
    assert square_service.needs_token_refresh(org) is False


def test_needs_token_refresh_true_within_the_recommended_window():
    org = Organization(id=1, name="Test", webhook_secret="x")  # noqa: S106 -- fake test value
    org.square_access_token = "EAAA-fake"  # noqa: S105 -- fake test value
    org.square_token_expires_at = datetime.now(timezone.utc) + timedelta(days=3)
    assert square_service.needs_token_refresh(org) is True


def test_needs_token_refresh_false_when_far_from_expiring():
    org = Organization(id=1, name="Test", webhook_secret="x")  # noqa: S106 -- fake test value
    org.square_access_token = "EAAA-fake"  # noqa: S105 -- fake test value
    org.square_token_expires_at = datetime.now(timezone.utc) + timedelta(days=20)
    assert square_service.needs_token_refresh(org) is False
