"""Where devices and registrations are stored. Swap SqliteDeviceRegistry for a real database later."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from .models import Device, Registration, RegistrationStatus


class DeviceRegistry(ABC):
    """Async so that a networked database can implement it without changing callers."""

    async def open(self) -> None:
        """Create tables / connections. Called by DeviceGateway.start()."""

    async def close(self) -> None:
        """Release resources. Called by DeviceGateway.stop()."""

    # Devices -------------------------------------------------------------
    @abstractmethod
    async def get_device(self, device_id: str) -> Device | None: ...

    @abstractmethod
    async def get_device_by_hw_id(self, hw_id: str) -> Device | None: ...

    @abstractmethod
    async def list_devices(self) -> list[Device]: ...

    @abstractmethod
    async def save_device(self, device: Device) -> None:
        """Insert or replace the whole device row (keyed by device_id)."""

    @abstractmethod
    async def delete_device(self, device_id: str) -> None: ...

    @abstractmethod
    async def touch(self, device_id: str, at: datetime, online: bool | None = None) -> None:
        """Update last_seen (and online when given) without rewriting the rest."""

    # Registrations -------------------------------------------------------
    @abstractmethod
    async def get_registration(self, hw_id: str) -> Registration | None: ...

    @abstractmethod
    async def list_registrations(self, status: RegistrationStatus | None = None) -> list[Registration]: ...

    @abstractmethod
    async def save_registration(self, registration: Registration) -> None:
        """Insert or replace (keyed by hw_id)."""


class SqliteDeviceRegistry(DeviceRegistry):
    """Single-file SQLite store for the temporary server. JSON columns hold sensors/commands."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

