
from sqlalchemy.orm import Session

from .. import models


def record_change(
    db: Session,
    user_id: str | None,
    action: str,
    target: str | None,
    result: str = "success"
) -> None:
    db.add(models.AuditLog(
        user_id=user_id,
        action=action,
        target=target,
        result=result
    ))


def get_audit_logs(
    db: Session,
    limit: int = 100,
    offset: int = 0
):
    return (
        db.query(models.AuditLog)
        .order_by(models.AuditLog.ts.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
