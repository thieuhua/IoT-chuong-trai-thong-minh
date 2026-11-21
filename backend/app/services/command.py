"""Persist command attempts and dispatch them through the injected gateway."""
import asyncio
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from .audit import record_change


def create_command(db: Session, device_id: str, user_id: str, action: str, params):
    row = models.Command(
        command_id=str(uuid.uuid4()), device_id=device_id, user_id=user_id,
        action=action, params=params, status="pending", issued_at=datetime.utcnow(),
    )
    db.add(row)
    record_change(db, user_id, "command.create", f"commands:{row.command_id}")
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return row


async def execute_command(db, gateway, device_id, user_id, action, params=None, timeout_s=None):
    row = create_command(db, device_id, user_id, action, params)
    try:
        result = await gateway.send_command(device_id, action, params, timeout_s)
    except (Exception, asyncio.CancelledError):
        row.status = "failed"
        row.acked_at = datetime.utcnow()
        db.commit()
        raise
    row.status = "success"
    row.acked_at = datetime.utcnow()
    db.commit()
    return row, result


async def send_command(db: Session, gateway, barn_id: str, user_id: str, body):
    # A barn command targets its first device, ordered consistently. The gateway
    # owns online/lifecycle validation; ORM status is "online", not "active".
    target = (db.query(models.Device).filter(models.Device.barn_id == barn_id)
              .order_by(models.Device.device_id).first())
    if target is None:
        raise HTTPException(404, "No device found in this barn")
    row, _ = await execute_command(
        db, gateway, target.device_id, user_id, body.action, body.params,
    )
    return row


def get_commands(db: Session, barn_id: str):
    return (db.query(models.Command)
            .join(models.Device, models.Command.device_id == models.Device.device_id)
            .filter(models.Device.barn_id == barn_id)
            .order_by(models.Command.issued_at.desc(), models.Command.command_id.desc())
            .all())
