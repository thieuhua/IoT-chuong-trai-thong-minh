
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from .audit import record_change


def get_alerts(
    db: Session,
    current_user,
    status_filter: str | None = None
):
    query = db.query(models.Alert)

    if current_user.role != "Admin":
        query = (
            query
            .join(
                models.Device,
                models.Alert.device_id == models.Device.device_id
            )
            .join(
                models.BarnAssignment,
                models.Device.barn_id == models.BarnAssignment.barn_id
            )
            .filter(
                models.BarnAssignment.user_id == current_user.id
            )
        )

    if status_filter:
        if status_filter not in ["open", "acknowledged", "closed"]:
            raise HTTPException(400, "Invalid alert status")

        query = query.filter(
            models.Alert.status == status_filter
        )

    return query.order_by(
        models.Alert.raised_at.desc()
    ).all()


def acknowledge_alert(
    db: Session,
    alert_id: str,
    current_user,
    note: str | None = None
):
    target_alert = db.query(models.Alert).filter(
        models.Alert.id == alert_id
    ).first()

    if not target_alert:
        raise HTTPException(404, "Alert not found")

    if target_alert.status == "closed":
        raise HTTPException(
            409,
            "Cannot acknowledge a closed alert"
        )

    changed = (
        target_alert.status != "acknowledged"
        or target_alert.handled_by != current_user.id
        or target_alert.note != note
    )
    target_alert.status = "acknowledged"
    target_alert.handled_by = current_user.id
    target_alert.note = note

    if changed:
        record_change(db, current_user.id, "alert.acknowledge", f"alerts:{alert_id}")
        db.commit()
        db.refresh(target_alert)

    return target_alert


def close_alert(
    db: Session,
    alert_id: str,
    current_user,
    note: str | None = None
):
    target_alert = db.query(models.Alert).filter(
        models.Alert.id == alert_id
    ).first()

    if not target_alert:
        raise HTTPException(404, "Alert not found")

    if target_alert.status == "closed":
        raise HTTPException(
            409,
            "Alert is already closed"
        )

    target_alert.status = "closed"
    target_alert.handled_by = current_user.id
    target_alert.note = note
    target_alert.closed_at = datetime.utcnow()

    record_change(db, current_user.id, "alert.close", f"alerts:{alert_id}")
    db.commit()
    db.refresh(target_alert)

    return target_alert
