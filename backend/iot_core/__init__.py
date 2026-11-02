"""Device communication layer: import DeviceGateway and call its methods; MQTT stays inside."""

from .config import AuthMode, GatewayConfig
from .errors import (BrokerAuthError, CommandFailed, CommandTimeout, DeviceNotFound, DeviceOffline,
                     InvalidState, IotError, RegistrationNotFound)
from .gateway import DeviceGateway
from .models import (Device, Readings, Registration, RegistrationStatus, SensorSpec, StatusEvent,
                     TelemetryRecord)

__all__ = [
    "AuthMode", "GatewayConfig", "DeviceGateway",
    "Device", "Readings", "Registration", "RegistrationStatus", "SensorSpec", "StatusEvent",
    "TelemetryRecord",
    "IotError", "BrokerAuthError", "CommandFailed", "CommandTimeout", "DeviceNotFound",
    "DeviceOffline", "InvalidState", "RegistrationNotFound",
]
