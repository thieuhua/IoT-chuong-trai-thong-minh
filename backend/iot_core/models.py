"""Plain data objects returned by DeviceGateway. No MQTT or storage details leak out of here."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class RegistrationStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


@dataclass
class SensorSpec:
    name: str
    driver: str
    fields: dict[str, str] = field(default_factory=dict)  # field name -> unit

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SensorSpec:
        return cls(name=str(raw["name"]), driver=str(raw.get("driver", "")),
                   fields={str(k): str(v) for k, v in dict(raw.get("fields", {})).items()})

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "driver": self.driver, "fields": dict(self.fields)}


@dataclass
class Device:
    device_id: str
    hw_id: str
    name: str = ""
    model: str = ""
    fw: str = ""
    sensors: list[SensorSpec] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    interval_s: int | None = None
    online: bool = False
    last_seen: datetime | None = None
    registered_at: datetime | None = None

    def sensor(self, name: str) -> SensorSpec | None:
        return next((s for s in self.sensors if s.name == name), None)


@dataclass
class Registration:
    """A provisioning request, keyed by hw_id.

    `password` (plain) is kept only while pending, because the broker account is created on approval.
    `password_hash` (sha256 hex) stays, so a device that missed its "approved" response and asks again
    with the same password gets "approved" again, while a different password means re-registration.
    """

    hw_id: str
    status: RegistrationStatus
    requested_at: datetime
    updated_at: datetime
    model: str = ""
    fw: str = ""
    sensors: list[SensorSpec] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    device_id: str | None = None
    reason: str | None = None
    password: str | None = None
    password_hash: str | None = None


@dataclass
class Readings:
    """Sensor values grouped by sensor name, as in telemetry data."""

    values: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> Readings:
        return cls(values=dict(data.get("readings") or {}), errors=dict(data.get("errors") or {}))


@dataclass
class TelemetryRecord:
    device_id: str
    received_at: datetime
    device_ts: float | None
    readings: Readings


@dataclass
class StatusEvent:
    device_id: str
    online: bool
    reason: str | None
    at: datetime
