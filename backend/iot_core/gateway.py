"""DeviceGateway: the only object a server needs to talk to ESP32 devices.

    async with DeviceGateway.from_config(GatewayConfig.from_env("deployment/.env")) as gw:
        for device in await gw.list_devices(online=True):
            print(device.device_id, await gw.read_all(device.device_id))

All methods are coroutines and must be called from the event loop the gateway was started on.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, TypeVar

from . import protocol
from .broker_auth import BrokerAuth
from .config import GatewayConfig
from .errors import (CommandFailed, CommandTimeout, DeviceNotFound, DeviceOffline,
                     InvalidState, RegistrationNotFound)
from .models import (Device, Readings, Registration, RegistrationStatus, SensorSpec,
                     StatusEvent, TelemetryRecord)
from .provisioning import handle_request, reply
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
        self._pending: dict[str, tuple[str, asyncio.Future[dict[str, Any]]]] = {}
        self._events = {key: [] for key in ("telemetry", "status", "registration", "device")}
        self._provision_lock = asyncio.Lock()
        self._started = False

    @classmethod
    def from_config(cls, config: GatewayConfig) -> DeviceGateway:
        """Default wiring: paho transport, SQLite registry + telemetry, NoAuth or DynSecAuth by auth_mode."""
        from .broker_auth import DynSecAuth, NoAuth
        from .config import AuthMode
        from .registry import SqliteDeviceRegistry
        from .telemetry import SqliteTelemetryStore
        transport = MqttTransport(config.broker_host, config.broker_port,
                                  username=config.username, password=config.password,
                                  client_id=config.client_id_prefix, connect_timeout_s=config.connect_timeout_s)
        return cls(config, transport=transport, registry=SqliteDeviceRegistry(config.db_path),
                   telemetry=SqliteTelemetryStore(config.db_path),
                   broker_auth=DynSecAuth(transport) if config.auth_mode == AuthMode.DYNSEC else NoAuth())

    # Lifecycle -------------------------------------------------------------
    async def start(self) -> None:
        """Open stores, connect, subscribe to protocol.BACKEND_SUBSCRIPTIONS.

        On (re)connect every device is first marked offline; retained status messages then
        restore the real state.
        """
        if self._started:
            return
        await self.registry.open()
        await self.telemetry.open()
        self.transport.on_connection_change(self._connection_changed)
        try:
            await self.transport.start()
            await self.broker_auth.start()
            for topic in protocol.BACKEND_SUBSCRIPTIONS:
                # resp must not queue behind an ordered handler (or event callback) that awaits it.
                ordered = not topic.endswith("/" + protocol.RESP)
                await self.transport.subscribe(topic, self._message, qos=1, ordered=ordered)
            self._started = True
        except BaseException:
            await self.stop()
            raise

    async def stop(self) -> None:
        """Cancel pending commands (CommandTimeout), disconnect, close stores."""
        for _, future in list(self._pending.values()):
            if not future.done():
                future.set_exception(CommandTimeout("Gateway stopped"))
        self._pending.clear()
        try:
            await self.transport.stop()
        finally:
            await self.telemetry.close()
            await self.registry.close()
            self._started = False

    async def __aenter__(self) -> DeviceGateway:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    # Devices -----------------------------------------------------------------
    async def list_devices(self, online: bool | None = None) -> list[Device]:
        return [device for device in await self.registry.list_devices()
                if online is None or device.online == online]

    async def get_device(self, device_id: str) -> Device:
        """Raise DeviceNotFound."""
        device = await self.registry.get_device(device_id)
        if device is None:
            raise DeviceNotFound(device_id)
        return device

    async def rename(self, device_id: str, name: str) -> Device:
        device = await self.get_device(device_id)
        device.name = name
        await self.registry.save_device(device)
        await self._emit("device", device)
        return device

    # Live operations (cmd -> resp) ----------------------------------------------
    async def send_command(self, device_id: str, name: str, args: dict[str, Any] | None = None,
                           timeout_s: float | None = None) -> dict[str, Any]:
        """Publish a cmd (QoS 1) and wait for the resp with matching `re`.

        Raises DeviceNotFound (unknown or revoked), DeviceOffline (known but offline: no publish),
        CommandTimeout (no answer within timeout_s or config.command_timeout_s),
        CommandFailed (ok=false). Returns resp.data.result.
        """
        device = await self.get_device(device_id)
        if not device.online:
            raise DeviceOffline(device_id)
        timeout = self.config.command_timeout_s if timeout_s is None else timeout_s
        if timeout <= 0:
            raise ValueError("timeout_s must be positive")
        message = protocol.command(name, args)
        future = asyncio.get_running_loop().create_future()
        self._pending[message.id] = (device_id, future)
        try:
            async with asyncio.timeout(timeout):
                await self.transport.publish(protocol.device_topic(device_id, protocol.CMD), message.encode(), qos=1)
                return await future
        except TimeoutError as exc:
            raise CommandTimeout(f"{device_id}: {name}") from exc
        finally:
            self._pending.pop(message.id, None)

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
        result = await self.send_command(device_id, "read", {"sensor": sensor})
        if sensor in (result.get("errors") or {}):
            raise CommandFailed(protocol.ERR_SENSOR_ERROR, result["errors"][sensor])
        if sensor not in (result.get("readings") or {}):
            raise CommandFailed(protocol.ERR_SENSOR_NOT_FOUND)
        return result["readings"][sensor]

    async def set_interval(self, device_id: str, seconds: int) -> int:
        """Change telemetry period (1..3600); updates the stored device too."""
        if isinstance(seconds, bool) or not isinstance(seconds, int) or not 1 <= seconds <= 3600:
            raise ValueError("seconds must be between 1 and 3600")
        result = await self.send_command(device_id, "set_interval", {"seconds": seconds})
        device = await self.get_device(device_id)
        device.interval_s = result["interval_s"]
        await self.registry.save_device(device)
        await self._emit("device", device)
        return device.interval_s

    async def reboot(self, device_id: str) -> None:
        await self.send_command(device_id, "reboot")

    # Stored data -----------------------------------------------------------------
    async def latest_telemetry(self, device_id: str) -> TelemetryRecord | None:
        await self.get_device(device_id)
        return await self.telemetry.latest(device_id)

    async def telemetry_history(self, device_id: str, limit: int = 100,
                                since: datetime | None = None) -> list[TelemetryRecord]:
        await self.get_device(device_id)
        return await self.telemetry.history(device_id, limit, since)

    # Registration ------------------------------------------------------------------
    async def list_registrations(self, status: RegistrationStatus | None = RegistrationStatus.PENDING
                                 ) -> list[Registration]:
        return await self.registry.list_registrations(status)

    async def approve(self, hw_id: str, *, device_id: str | None = None, name: str = "") -> Device:
        """Approve a pending registration.

        device_id defaults to protocol.default_device_id(hw_id). Creates the broker account with the
        password the device sent, saves the Device, clears the stored password, then publishes
        provision.response approved. Raises RegistrationNotFound, InvalidState (not pending),
        ValueError (bad or already-used device_id).
        """
        async with self._provision_lock:
            return await self._approve(hw_id, device_id=device_id, name=name)

    async def reject(self, hw_id: str, reason: str = "") -> Registration:
        async with self._provision_lock:
            registration = await self.registry.get_registration(hw_id)
            if registration is None:
                raise RegistrationNotFound(hw_id)
            if registration.status not in (RegistrationStatus.PENDING, RegistrationStatus.REJECTED):
                raise InvalidState(registration.status.value)
            registration.status = RegistrationStatus.REJECTED
            registration.reason = reason
            registration.updated_at = datetime.now(timezone.utc)
            await self.registry.save_registration(registration)
            await reply(self, registration)
            return registration

    async def revoke(self, device_id: str) -> None:
        """Remove the broker account, clear retained status/meta (empty retained publish),
        delete the device and its telemetry, mark the registration revoked."""
        device = await self.get_device(device_id)
        await self.broker_auth.remove_device_account(device_id)
        for leaf in (protocol.STATUS, protocol.META):
            await self.transport.publish(protocol.device_topic(device_id, leaf), b"", qos=1, retain=True)
        await self.registry.delete_device(device_id)
        await self.telemetry.delete_device(device_id)
        registration = await self.registry.get_registration(device.hw_id)
        if registration:
            registration.status = RegistrationStatus.REVOKED
            registration.password = None
            registration.updated_at = datetime.now(timezone.utc)
            await self.registry.save_registration(registration)

    # Events ----------------------------------------------------------------------
    # Callbacks may be sync or async; an exception in one is logged and does not affect others.
    def on_telemetry(self, callback: Callback[TelemetryRecord]) -> Unsubscribe:
        return self._subscribe_event("telemetry", callback)

    def on_status_change(self, callback: Callback[StatusEvent]) -> Unsubscribe:
        """Fires only when online actually changes."""
        return self._subscribe_event("status", callback)

    def on_registration(self, callback: Callback[Registration]) -> Unsubscribe:
        """Fires when a new or changed registration request arrives (not on repeated identical requests)."""
        return self._subscribe_event("registration", callback)

    def on_device_updated(self, callback: Callback[Device]) -> Unsubscribe:
        """Fires after meta changes the stored device (sensors, fw, interval)."""
        return self._subscribe_event("device", callback)

    async def _approve(self, hw_id: str, *, device_id: str | None = None, name: str = "") -> Device:
        registration = await self.registry.get_registration(hw_id)
        if registration is None:
            raise RegistrationNotFound(hw_id)
        if registration.status not in (RegistrationStatus.PENDING, RegistrationStatus.REJECTED):
            raise InvalidState(registration.status.value)
        if not registration.password:
            raise InvalidState("Registration has no password")
        device_id = device_id if device_id is not None else protocol.default_device_id(hw_id)
        if not protocol.is_valid_device_id(device_id):
            raise ValueError("Invalid device_id")
        owner = await self.registry.get_device(device_id)
        if owner and owner.hw_id != hw_id:
            raise ValueError("device_id already used")
        previous = await self.registry.get_device_by_hw_id(hw_id)
        if previous and previous.device_id != device_id:
            await self.revoke(previous.device_id)
        await self.broker_auth.create_device_account(device_id, registration.password)
        device = Device(device_id, hw_id, name=name or (previous.name if previous else ""),
                        model=registration.model, fw=registration.fw, sensors=registration.sensors,
                        commands=registration.commands,
                        registered_at=previous.registered_at if previous else datetime.now(timezone.utc))
        await self.registry.save_device(device)
        registration.status = RegistrationStatus.APPROVED
        registration.device_id = device_id
        registration.password = None
        registration.reason = None
        registration.updated_at = datetime.now(timezone.utc)
        await self.registry.save_registration(registration)
        await reply(self, registration)
        return device

    async def _connection_changed(self, connected: bool) -> None:
        if connected:
            for device in await self.registry.list_devices():
                device.online = False
                await self.registry.save_device(device)

    async def _message(self, topic: str, payload: bytes) -> None:
        info = protocol.parse_topic(topic)
        if info is None or (info.kind == protocol.STATUS and not payload):
            return
        try:
            envelope = protocol.Envelope.decode(payload, expected_type=info.kind)
        except protocol.ProtocolError:
            logging.getLogger("iot_core").warning("Invalid envelope on %s", topic)
            return
        data = envelope.data
        if info.kind == protocol.PROVISION_REQUEST:
            await handle_request(self, info.key, data)
            return
        device = await self.registry.get_device(info.key)
        if device is None:
            logging.getLogger("iot_core").debug("Unknown device on %s", topic)
            return
        now = datetime.now(timezone.utc)
        if info.kind == protocol.STATUS:
            if data.get("state") not in ("online", "offline"):
                logging.getLogger("iot_core").warning("Invalid status on %s", topic)
                return
            online = data["state"] == "online"
            await self.registry.touch(info.key, now, online=online)
            if device.online != online:
                await self._emit("status", StatusEvent(info.key, online, data.get("reason"), now))
        elif info.kind == protocol.META:
            try:
                for key in ("model", "fw", "commands", "interval_s"):
                    if key in data:
                        setattr(device, key, data[key])
                if "sensors" in data:
                    device.sensors = [SensorSpec.from_dict(s) for s in data["sensors"]]
            except (KeyError, ValueError, TypeError):
                logging.getLogger("iot_core").warning("Invalid meta on %s", topic)
                return
            await self.registry.save_device(device)
            await self._emit("device", device)
        elif info.kind == protocol.TELEMETRY:
            record = TelemetryRecord(info.key, now, envelope.ts, Readings.from_data(data))
            await self.telemetry.append(record)
            await self.registry.touch(info.key, now, online=True)
            if not device.online:
                await self._emit("status", StatusEvent(info.key, True, None, now))
            await self._emit("telemetry", record)
        elif info.kind == protocol.RESP:
            pending = self._pending.get(data.get("re"))
            if pending and pending[0] == info.key and not pending[1].done():
                if data.get("ok") is True:
                    pending[1].set_result(data.get("result", {}))
                else:
                    error = data.get("error") or {}
                    pending[1].set_exception(CommandFailed(error.get("code", "internal"),
                                                          error.get("message", "")))

    def _subscribe_event(self, key: str, callback) -> Unsubscribe:
        self._events[key].append(callback)
        def unsubscribe():
            if callback in self._events[key]:
                self._events[key].remove(callback)
        return unsubscribe

    async def _emit(self, key: str, value) -> None:
        for callback in tuple(self._events[key]):
            try:
                result = callback(value)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logging.getLogger("iot_core").exception("Event callback failed: %s", key)
