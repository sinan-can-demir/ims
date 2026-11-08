# tests/test_square_api.py

from urllib.parse import parse_qs, urlparse

from app.services import square_service


def _callback(client):
    # follow_redirects=False: the redirect target is what's under test.
    return client.get(
        "/api/square/callback",
        params={"code": "any-code", "state": "any-state"},
        follow_redirects=False,
    )


def test_callback_error_redirect_url_encodes_the_message(client, monkeypatch):
    # The error text is built from exception messages that can include
    # Square's raw response body. Unencoded, "&" and "#" let that text add
    # query parameters to (or truncate) the redirect URL -- e.g. a message
    # containing "&square_connected=true" would look like a successful connect.
    message = 'bad state & square_connected=true #frag "q" 100% done'

    def boom(state):
        raise square_service.SquareOAuthError(message)

    monkeypatch.setattr(square_service, "verify_state", boom)

    response = _callback(client)

    assert response.status_code in (302, 307)
    target = urlparse(response.headers["location"])
    assert target.fragment == ""
    assert parse_qs(target.query) == {"square_error": [message]}


def test_callback_success_redirects_with_square_connected(client, monkeypatch):
    monkeypatch.setattr(square_service, "verify_state", lambda state: 1)
    monkeypatch.setattr(square_service, "exchange_code_for_token", lambda code, uri: {})
    monkeypatch.setattr(square_service, "save_connection", lambda db, org_id, token: None)

    response = _callback(client)

    assert response.status_code in (302, 307)
    assert parse_qs(urlparse(response.headers["location"]).query) == {"square_connected": ["true"]}
