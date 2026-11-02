"""Where telemetry is kept. Swap for a time-series database later."""

from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from ._storage import dumps, utc
from .models import Readings, TelemetryRecord


class TelemetryStore(ABC):
    async def open(self) -> None:
        """Create tables / connections."""

    async def close(self) -> None:
        """Release resources."""

    @abstractmethod
    async def append(self, record: TelemetryRecord) -> None: ...

    @abstractmethod
    async def latest(self, device_id: str) -> TelemetryRecord | None: ...

    @abstractmethod
    async def history(self, device_id: str, limit: int = 100,
                      since: datetime | None = None) -> list[TelemetryRecord]:
        """Newest first."""

    @abstractmethod
    async def delete_device(self, device_id: str) -> None: ...


class SqliteTelemetryStore(TelemetryStore):
    def __init__(self, path: str | Path, keep_per_device: int = 10_000):
        self.path = Path(path)
        self.keep_per_device = keep_per_device

    async def open(self) -> None:
        if self.keep_per_device < 1:
            raise ValueError("keep_per_device must be positive")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY, device_id TEXT NOT NULL,
                received_at TEXT NOT NULL, device_ts REAL, readings TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS telemetry_device_time
                ON telemetry(device_id, received_at DESC, id DESC);
        """)
        self._db.commit()

    async def close(self) -> None:
        self._db.close()

    async def append(self, record: TelemetryRecord) -> None:
        self._db.execute("INSERT INTO telemetry(device_id,received_at,device_ts,readings) VALUES(?,?,?,?)",
                         (record.device_id, utc(record.received_at), record.device_ts, dumps(record.readings)))
        self._db.execute("DELETE FROM telemetry WHERE device_id=? AND id NOT IN "
                         "(SELECT id FROM telemetry WHERE device_id=? "
                         "ORDER BY received_at DESC, id DESC LIMIT ?)",
                         (record.device_id, record.device_id, self.keep_per_device))
        self._db.commit()

    async def latest(self, device_id: str) -> TelemetryRecord | None:
        rows = await self.history(device_id, 1)
        return rows[0] if rows else None

    async def history(self, device_id: str, limit: int = 100,
                      since: datetime | None = None) -> list[TelemetryRecord]:
        if limit < 1:
            raise ValueError("limit must be positive")
        sql = "SELECT device_id,received_at,device_ts,readings FROM telemetry WHERE device_id=?"
        params = [device_id]
        if since is not None:
            sql += " AND received_at>=?"
            params.append(utc(since))
        sql += " ORDER BY received_at DESC,id DESC LIMIT ?"
        params.append(limit)
        return [TelemetryRecord(row[0], datetime.fromisoformat(row[1]), row[2],
                                Readings(**json.loads(row[3]))) for row in self._db.execute(sql, params)]

    async def delete_device(self, device_id: str) -> None:
        self._db.execute("DELETE FROM telemetry WHERE device_id=?", (device_id,))
        self._db.commit()
