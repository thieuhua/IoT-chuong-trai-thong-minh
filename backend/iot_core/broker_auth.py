"""Broker account management for devices (docs/protocol.md section 8)."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from . import protocol
from .errors import BrokerAuthError

if TYPE_CHECKING:
    from .transport import MqttTransport


class BrokerAuth(ABC):
    async def start(self) -> None:
        """Subscribe to account-management responses when needed."""

    @abstractmethod
    async def create_device_account(self, device_id: str, password: str) -> None:
        """Create (or update the password of) the MQTT account for an approved device. Idempotent."""

    @abstractmethod
    async def remove_device_account(self, device_id: str) -> None:
        """Delete the account; the broker disconnects the device. Missing account is not an error."""


class NoAuth(BrokerAuth):
    """Anonymous broker: nothing to create."""

    async def create_device_account(self, device_id: str, password: str) -> None:
        return None

    async def remove_device_account(self, device_id: str) -> None:
        return None


class DynSecAuth(BrokerAuth):
    """Mosquitto Dynamic Security over MQTT ($CONTROL/dynamic-security/v1).

    Per device: role `dev-{id}` with literal ACLs (publishClientSend on status/meta/telemetry/resp,
    subscribeLiteral on cmd), client `{id}` with clientid pinned to `{id}`.
    Mosquitto 2.0 does not expand %c in ACLs, hence one role per device.
    """

    CONTROL_TOPIC = "$CONTROL/dynamic-security/v1"
    RESPONSE_TOPIC = "$CONTROL/dynamic-security/v1/response"

    def __init__(self, transport: MqttTransport, timeout_s: float = 5.0):
        self.transport = transport
        self.timeout_s = timeout_s
        self._pending: dict[str, asyncio.Future[dict]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def start(self) -> None:
        # Unordered: gateway handlers (auto-approve) wait for these replies.
        await self.transport.subscribe(self.RESPONSE_TOPIC, self._response, qos=1, ordered=False)

    def _lock(self, device_id: str) -> asyncio.Lock:
        return self._locks.setdefault(device_id, asyncio.Lock())

    def _response(self, topic: str, payload: bytes) -> None:
        try:
            for response in json.loads(payload).get("responses", []):
                future = self._pending.get(response.get("correlationData"))
                if future is not None and not future.done():
                    future.set_result(response)
        except (ValueError, TypeError, AttributeError):
            logging.getLogger("iot_core").warning("Invalid DynSec response")

    async def _command(self, command: str, **kwargs) -> dict:
        correlation = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self._pending[correlation] = future
        try:
            payload = json.dumps({"commands": [dict(command=command, correlationData=correlation, **kwargs)]})
            async with asyncio.timeout(self.timeout_s):
                await self.transport.publish(self.CONTROL_TOPIC, payload.encode(), qos=1)
                return await future
        except TimeoutError as exc:
            raise BrokerAuthError(f"DynSec {command} timed out") from exc
        except ConnectionError as exc:
            raise BrokerAuthError(f"DynSec {command}: {exc}") from exc
        finally:
            self._pending.pop(correlation, None)

    async def _checked(self, command: str, *, allowed: tuple[str, ...] = (), **kwargs) -> dict:
        response = await self._command(command, **kwargs)
        error = response.get("error")
        if error and error not in allowed:
            raise BrokerAuthError(f"{command}: {error}")
        return response

    async def create_device_account(self, device_id: str, password: str) -> None:
        async with self._lock(device_id):
            await self._create(device_id, password)

    async def _create(self, device_id: str, password: str) -> None:
        role = f"dev-{device_id}"
        await self._checked("createRole", rolename=role, allowed=("Role already exists",))
        for leaf in (*protocol.DEVICE_LEAVES, protocol.CMD):
            await self._checked("addRoleACL", rolename=role,
                                acltype="subscribeLiteral" if leaf == protocol.CMD else "publishClientSend",
                                topic=protocol.device_topic(device_id, leaf), allow=True, priority=0,
                                allowed=("ACL with this topic already exists",))
        response = await self._checked("createClient", username=device_id, password=password,
                                       clientid=device_id, roles=[{"rolename": role}],
                                       allowed=("Client already exists",))
        if response.get("error"):
            await self._checked("setClientPassword", username=device_id, password=password)
            await self._checked("setClientId", username=device_id, clientid=device_id)
            current = await self._checked("getClient", username=device_id)
            roles = current.get("data", {}).get("client", {}).get("roles", [])
            # Mosquitto 2.0.22 reports "Internal error" for a duplicate membership, so only add when missing.
            if not any(item.get("rolename") == role for item in roles):
                await self._checked("addClientRole", username=device_id, rolename=role)

    async def remove_device_account(self, device_id: str) -> None:
        async with self._lock(device_id):
            await self._checked("deleteClient", username=device_id, allowed=("Client not found",))
            await self._checked("deleteRole", rolename=f"dev-{device_id}", allowed=("Role not found",))
