"""DeviceGateway: the only object a server needs to talk to ESP32 devices.

    async with DeviceGateway.from_config(GatewayConfig.from_env("deployment/.env")) as gw:
        for device in await gw.list_devices(online=True):
            print(device.device_id, await gw.read_all(device.device_id))

All methods are coroutines and must be called from the event loop the gateway was started on.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, TypeVar

from .broker_auth import BrokerAuth
from .config import GatewayConfig
from .models import Device, Readings, Registration, RegistrationStatus, StatusEvent, TelemetryRecord
from .registry import DeviceRegistry
from .telemetry import TelemetryStore
from .transport import MqttTransport

T = TypeVar("T")
Callback = Callable[[T], "Awaitable[None] | None"]
Unsubscribe = Callable[[], None]


class DeviceGateway:
    def __init__(self, config: GatewayConfig, *, transport: MqttTransport,
                 registry: DeviceRegistry, telemetry: TelemetryStore, broker_auth: BrokerAuth):
        """Dependencies are injected so a real server can swap storage or broker auth."""
        self.config = config
        self.transport = transport
        self.registry = registry
        self.telemetry = telemetry
        self.broker_auth = broker_auth

    @classmethod
    def from_config(cls, config: GatewayConfig) -> DeviceGateway:
        """Default wiring: paho transport, SQLite registry + telemetry, NoAuth or DynSecAuth by auth_mode."""
        raise NotImplementedError

    # Lifecycle -------------------------------------------------------------
    async def start(self) -> None:
        """Open stores, connect, subscribe to protocol.BACKEND_SUBSCRIPTIONS.

        On (re)connect every device is first marked offline; retained status messages then
        restore the real state.
        """
        raise NotImplementedError

    async def stop(self) -> None:
        """Cancel pending commands (CommandTimeout), disconnect, close stores."""
        raise NotImplementedError

    async def __aenter__(self) -> DeviceGateway:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    # Devices -----------------------------------------------------------------
    async def list_devices(self, online: bool | None = None) -> list[Device]:
        raise NotImplementedError

    async def get_device(self, device_id: str) -> Device:
        """Raise DeviceNotFound."""
        raise NotImplementedError

    async def rename(self, device_id: str, name: str) -> Device:
        raise NotImplementedError

    # Live operations (cmd -> resp) ----------------------------------------------
    async def send_command(self, device_id: str, name: str, args: dict[str, Any] | None = None,
                           timeout_s: float | None = None) -> dict[str, Any]:
        """Publish a cmd (QoS 1) and wait for the resp with matching `re`.

        Raises DeviceNotFound (unknown or revoked), DeviceOffline (known but offline: no publish),
        CommandTimeout (no answer within timeout_s or config.command_timeout_s),
        CommandFailed (ok=false). Returns resp.data.result.
        """
        raise NotImplementedError

    async def ping(self, device_id: str) -> dict[str, Any]:
        return await self.send_command(device_id, "ping")

    async def get_info(self, device_id: str) -> dict[str, Any]:
        return await self.send_command(device_id, "get_info")

    async def read_all(self, device_id: str) -> Readings:
        return Readings.from_data(await self.send_command(device_id, "read"))

    async def read_sensor(self, device_id: str, sensor: str) -> dict[str, Any]:
        """Fresh values of one sensor, e.g. {"temperature": 24, "humidity": 61}.

        Raises CommandFailed(sensor_not_found / sensor_error).
        """
        raise NotImplementedError

    async def set_interval(self, device_id: str, seconds: int) -> int:
        """Change telemetry period (1..3600); updates the stored device too."""
        raise NotImplementedError

    async def reboot(self, device_id: str) -> None:
        await self.send_command(device_id, "reboot")

    # Stored data -----------------------------------------------------------------
    async def latest_telemetry(self, device_id: str) -> TelemetryRecord | None:
        raise NotImplementedError

    async def telemetry_history(self, device_id: str, limit: int = 100,
                                since: datetime | None = None) -> list[TelemetryRecord]:
        raise NotImplementedError

    # Registration ------------------------------------------------------------------
    async def list_registrations(self, status: RegistrationStatus | None = RegistrationStatus.PENDING
                                 ) -> list[Registration]:
        raise NotImplementedError

    async def approve(self, hw_id: str, *, device_id: str | None = None, name: str = "") -> Device:
        """Approve a pending registration.

        device_id defaults to protocol.default_device_id(hw_id). Creates the broker account with the
        password the device sent, saves the Device, clears the stored password, then publishes
        provision.response approved. Raises RegistrationNotFound, InvalidState (not pending),
        ValueError (bad or already-used device_id).
        """
        raise NotImplementedError

    async def reject(self, hw_id: str, reason: str = "") -> Registration:
        raise NotImplementedError

    async def revoke(self, device_id: str) -> None:
        """Remove the broker account, clear retained status/meta (empty retained publish),
        delete the device and its telemetry, mark the registration revoked."""
        raise NotImplementedError

    # Events ----------------------------------------------------------------------
    # Callbacks may be sync or async; an exception in one is logged and does not affect others.
    def on_telemetry(self, callback: Callback[TelemetryRecord]) -> Unsubscribe:
        raise NotImplementedError

    def on_status_change(self, callback: Callback[StatusEvent]) -> Unsubscribe:
        """Fires only when online actually changes."""
        raise NotImplementedError

    def on_registration(self, callback: Callback[Registration]) -> Unsubscribe:
        """Fires when a new or changed registration request arrives (not on repeated identical requests)."""
        raise NotImplementedError

    def on_device_updated(self, callback: Callback[Device]) -> Unsubscribe:
        """Fires after meta changes the stored device (sensors, fw, interval)."""
        raise NotImplementedError
