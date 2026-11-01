# tests/test_cors.py

"""CORS allow-list for the webview origins the desktop/mobile clients
present (#364, SEC-5). Nothing exercised app/main.py's allow_origin_regex
before this, so a regression there would break the Windows desktop app
(WebView2 presents http://tauri.localhost) with every test still green.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def _preflight(origin: str):
    # Mirrors the real first request the desktop app makes
    # (tauri/src/main.js's register call): a cross-origin POST with a JSON
    # body, which the webview always preflights.
    return client.options(
        "/api/auth/register",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


@pytest.mark.parametrize(
    "origin",
    [
        # Windows WebView2 release build and Android webview (#232).
        "http://tauri.localhost",
        # Linux/macOS desktop release build (custom URL scheme).
        "tauri://localhost",
        # `cargo tauri dev` debug build's loopback server.
        "http://127.0.0.1:1430",
        "http://localhost:1430",
        # Default CORS_ORIGINS entry (the Streamlit dashboard).
        "http://localhost:8501",
    ],
)
def test_allowed_origin_preflight_succeeds(origin):
    response = _preflight(origin)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "content-type" in response.headers["access-control-allow-headers"].lower()


def test_allowed_origin_gets_allow_header_on_simple_request():
    response = client.get("/health", headers={"Origin": "http://tauri.localhost"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example.com",
        # Look-alikes of the allowed origins — the regex must be anchored,
        # not a substring/prefix match.
        "http://tauri.localhost.evil.example.com",
        "http://evil-tauri.localhost",
        "https://tauri.localhost",
        "http://tauri.localhost:8080",
        "http://localhost.evil.example.com",
        "tauri://localhost.evil.example.com",
    ],
)
def test_disallowed_origin_preflight_rejected(origin):
    response = _preflight(origin)

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_disallowed_origin_gets_no_allow_header_on_simple_request():
    response = client.get("/health", headers={"Origin": "http://evil.example.com"})

    assert "access-control-allow-origin" not in response.headers
