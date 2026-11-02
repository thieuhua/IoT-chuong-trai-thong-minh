"""Where telemetry is kept. Swap for a time-series database later."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from .models import TelemetryRecord


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

