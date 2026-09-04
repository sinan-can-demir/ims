from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def log_action(
    db: Session,
    actor_id: int | None,
    action: str,
    organization_id: int,
    detail: str | None = None,
) -> AuditLog:
    """
    Commits independently of whatever the caller does next — login_failed
    is logged right before the caller raises InvalidCredentialsError, and
    get_db() never commits on its own, so a shared transaction would lose
    the audit row the moment that exception unwinds the request.

    organization_id is required, not defaulted — it used to default to 1,
    which silently misattributed every call site that forgot to pass it
    (login_failed, po_submitted/po_received, role_changed) to org 1
    regardless of the real org involved. A caller with no real org to
    attribute to (e.g. a genuinely unknown login email) must pass an
    explicit fallback at that call site instead, so it reads as a
    deliberate choice rather than a silent default.
    """
    entry = AuditLog(
        actor_id=actor_id, action=action, detail=detail, organization_id=organization_id
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
