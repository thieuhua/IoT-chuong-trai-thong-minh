
import uuid

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from .audit import record_change


def send_command(
    db: Session,
    barn_id: str,
    user_id: str,
    body
):
    # Find device belonging to this barn
    target_device = db.query(models.Device).filter(
        models.Device.barn_id == barn_id
    ).first()

    if not target_device:
        raise HTTPException(
            404,
            "No device found in this barn"
        )

    if target_device.status != "active":
        raise HTTPException(
            409,
            "Device is not active"
        )

    command = models.Command(
        command_id=str(uuid.uuid4()),
        device_id=target_device.device_id,
        user_id=user_id,
        action=body.action,
        params=body.params,
        status="pending",
        issued_at=datetime.utcnow()
    )

    db.add(command)
    record_change(db, user_id, "command.create", f"commands:{command.command_id}")

    try:
        db.commit()
        db.refresh(command)
    except Exception:
        db.rollback()
        raise

    return command


def get_commands(db: Session, barn_id: str):
    return (
        db.query(models.Command)
        .join(
            models.Device,
            models.Command.device_id == models.Device.device_id
        )
        .filter(models.Device.barn_id == barn_id)
        .order_by(models.Command.issued_at.desc())
        .all()
    )
