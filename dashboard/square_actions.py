# dashboard/square_actions.py
#
# Square connector actions (ROADMAP.md's "Food Cost Visibility" Phase 3).
# get_connect_url()/get_connection_status()/disconnect() are read-only or
# in-process, same pattern as this app's other *_actions.py modules --
# but unlike those, the actual OAuth handshake can't happen in-process:
# it requires a real browser redirect through Square's own hosted login
# page and back, which only app/api/square.py's callback route (a real
# HTTP endpoint Square itself calls) can receive. This module only builds
# the link the dashboard shows for the user to click, and reads/clears
# connection state -- it never talks to Square directly.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.square import square_redirect_uri
from app.database import SessionLocal
from app.models.organization import Organization
from app.services import square_service


def get_connect_url(organization_id: int) -> str:
    return square_service.get_authorize_url(organization_id, square_redirect_uri())


def get_connection_status(organization_id: int) -> dict:
    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.id == organization_id).first()
        return {
            "connected": square_service.is_connected(org),
            "merchant_id": org.square_merchant_id,
            "needs_refresh": square_service.needs_token_refresh(org),
        }
    finally:
        db.close()


def disconnect(organization_id: int) -> None:
    db = SessionLocal()
    try:
        square_service.disconnect(db, organization_id)
    finally:
        db.close()
