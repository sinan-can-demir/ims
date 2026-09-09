# tests/test_dashboard_error_handling.py

from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.core.logging import logger
from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.user import User

from .utils import create_product, purchase

_REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_APP = str(_REPO_ROOT / "dashboard" / "app.py")


def _make_dashboard_user(dashboard_db) -> User:
    session = dashboard_db()
    try:
        user = User(
            email="dash-error-user@example.com",
            password_hash=hash_password("dash-error-password"),  # noqa: S106
            display_name="Dash Error User",
            role=UserRole.MEMBER,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user
    finally:
        session.close()


def _signed_in(at: AppTest, user: User) -> None:
    at.session_state["user"] = {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role.value,
        "organization_id": user.organization_id,
    }


def test_unhandled_page_exception_is_logged(client, dashboard_db, monkeypatch, caplog):
    product = create_product(client)
    purchase(client, product["id"], 50)
    user = _make_dashboard_user(dashboard_db)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("dashboard.data.forecast", _boom)
    monkeypatch.setattr("app.services.restock_service.forecast", _boom)

    at = AppTest.from_file(DASHBOARD_APP)
    _signed_in(at, user)

    with caplog.at_level("ERROR", logger=logger.name):
        at.run()

    # Streamlit's own error UI still surfaces the exception -- logging is
    # additive, not a replacement for that.
    assert at.exception

    records = [r for r in caplog.records if r.message == "unhandled_dashboard_exception"]
    assert len(records) == 1
    record = records[0]
    assert record.user_id == user.id
    assert record.organization_id == user.organization_id
    assert "RuntimeError: boom" in record.traceback
