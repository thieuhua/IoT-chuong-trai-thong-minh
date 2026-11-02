"""Provisioning request state transitions."""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from . import protocol
from .models import Registration, RegistrationStatus as State, SensorSpec

if TYPE_CHECKING:
    from .gateway import DeviceGateway

logger = logging.getLogger("iot_core")


async def reply(gateway: DeviceGateway, registration: Registration) -> None:
    message = protocol.provision_response(
        registration.status.value,
        registration.device_id if registration.status == State.APPROVED else None,
        registration.reason if registration.status == State.REJECTED else None)
    await gateway.transport.publish(protocol.provision_response_topic(registration.hw_id),
                                    message.encode(), qos=1, retain=False)


async def handle_request(gateway: DeviceGateway, hw_id: str, data: dict) -> None:
    password = data.get("password")
    if (data.get("hw_id") != hw_id or not isinstance(password, str)
            or not re.fullmatch(r"[0-9a-f]{16,64}", password)):
        logger.warning("Invalid provisioning request for %s", hw_id)
        return
    try:
        sensors = [SensorSpec.from_dict(s) for s in data.get("sensors", [])]
        commands = list(data.get("commands", []))
    except (KeyError, TypeError, ValueError):
        logger.warning("Invalid provisioning capabilities for %s", hw_id)
        return
    async with gateway._provision_lock:
        registration = await gateway.registry.get_registration(hw_id)
        digest = hashlib.sha256(password.encode()).hexdigest()
        if registration and registration.status == State.REJECTED:
            await reply(gateway, registration)
            return
        if registration and registration.status == State.APPROVED and registration.password_hash == digest:
            await reply(gateway, registration)
            return
        now = datetime.now(timezone.utc)
        if registration is None or registration.status == State.REVOKED:
            registration = Registration(hw_id, State.PENDING, now, now)
            changed = True
        else:
            changed = registration.status != State.PENDING
        updates = dict(model=data.get("model", ""), fw=data.get("fw", ""), sensors=sensors,
                       commands=commands, password=password, password_hash=digest)
        changed = changed or any(getattr(registration, key) != value for key, value in updates.items())
        for key, value in updates.items():
            setattr(registration, key, value)
        registration.status = State.PENDING
        registration.reason = None
        if changed:
            registration.updated_at = now
            await gateway.registry.save_registration(registration)
            await gateway._emit("registration", registration)
        if gateway.config.auto_approve:
            logger.warning("auto-approve is a development setting")
            await gateway._approve(hw_id)
        else:
            await reply(gateway, registration)
