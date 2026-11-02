"""Where devices and registrations are stored. Swap SqliteDeviceRegistry for a real database later."""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from ._storage import dumps, load_row
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

    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY, hw_id TEXT UNIQUE NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS registrations (
                hw_id TEXT PRIMARY KEY, status TEXT NOT NULL, data TEXT NOT NULL);
        """)
        self._db.commit()

    async def close(self) -> None:
        self._db.close()

    async def get_device(self, device_id: str) -> Device | None:
        row = self._db.execute("SELECT data FROM devices WHERE device_id=?", (device_id,)).fetchone()
        return load_row(row[0], Device) if row else None

    async def get_device_by_hw_id(self, hw_id: str) -> Device | None:
        row = self._db.execute("SELECT data FROM devices WHERE hw_id=?", (hw_id,)).fetchone()
        return load_row(row[0], Device) if row else None

    async def list_devices(self) -> list[Device]:
        return [load_row(row[0], Device) for row in self._db.execute(
            "SELECT data FROM devices ORDER BY device_id")]

    async def save_device(self, device: Device) -> None:
        self._db.execute("INSERT INTO devices VALUES(?,?,?) ON CONFLICT(device_id) DO UPDATE "
                         "SET hw_id=excluded.hw_id, data=excluded.data",
                         (device.device_id, device.hw_id, dumps(device)))
        self._db.commit()

    async def delete_device(self, device_id: str) -> None:
        self._db.execute("DELETE FROM devices WHERE device_id=?", (device_id,))
        self._db.commit()

    async def touch(self, device_id: str, at: datetime, online: bool | None = None) -> None:
        device = await self.get_device(device_id)
        if device:
            device.last_seen = at
            if online is not None:
                device.online = online
            await self.save_device(device)

    async def get_registration(self, hw_id: str) -> Registration | None:
        row = self._db.execute("SELECT data FROM registrations WHERE hw_id=?", (hw_id,)).fetchone()
        return load_row(row[0], Registration) if row else None

    async def list_registrations(self, status: RegistrationStatus | None = None) -> list[Registration]:
        rows = self._db.execute("SELECT data FROM registrations ORDER BY hw_id")
        registrations = [load_row(row[0], Registration) for row in rows]
        return [r for r in registrations if status is None or r.status == status]

    async def save_registration(self, registration: Registration) -> None:
        self._db.execute("INSERT INTO registrations VALUES(?,?,?) ON CONFLICT(hw_id) DO UPDATE "
                         "SET status=excluded.status, data=excluded.data",
                         (registration.hw_id, registration.status.value, dumps(registration)))
        self._db.commit()
