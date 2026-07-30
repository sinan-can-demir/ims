from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def log_action(
    db: Session,
    actor_id: int | None,
    action: str,
    detail: str | None = None,
    organization_id: int = 1,
) -> AuditLog:
    """
    Commits independently of whatever the caller does next — login_failed
    is logged right before the caller raises InvalidCredentialsError, and
    get_db() never commits on its own, so a shared transaction would lose
    the audit row the moment that exception unwinds the request.
    """
    entry = AuditLog(
        actor_id=actor_id, action=action, detail=detail, organization_id=organization_id
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
