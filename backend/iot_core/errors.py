"""Exceptions raised by DeviceGateway; the server layer maps them to HTTP errors."""


class IotError(Exception):
    """Base class for every error raised by iot_core."""


class DeviceNotFound(IotError):
    pass


class RegistrationNotFound(IotError):
    pass


class InvalidState(IotError):
    """Operation not allowed in the current state (e.g. approving a rejected request twice)."""


class DeviceOffline(IotError):
    pass


class CommandTimeout(IotError):
    pass


class CommandFailed(IotError):
    """The device answered ok=false. `code` is one of the protocol error codes."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.message = message


class BrokerAuthError(IotError):
    """The broker rejected an account change (Dynamic Security error)."""
