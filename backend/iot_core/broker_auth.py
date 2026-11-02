"""Broker account management for devices (docs/protocol.md section 8)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .transport import MqttTransport


class BrokerAuth(ABC):
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

