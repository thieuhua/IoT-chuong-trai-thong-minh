"""Topic and envelope rules from docs/protocol.md (v1). Keep in sync with firmware/src/core/protocol.py."""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

VERSION = 1
PREFIX = "iot/v1"
MAX_PAYLOAD = 4096

# Message types
PROVISION_REQUEST = "provision.request"
PROVISION_RESPONSE = "provision.response"
STATUS = "status"
META = "meta"
TELEMETRY = "telemetry"
CMD = "cmd"
RESP = "resp"

# Device-side topic leaves (iot/v1/{device_id}/{leaf})
DEVICE_LEAVES = (STATUS, META, TELEMETRY, RESP)

DEVICE_ID_RE = re.compile(r"^[a-z0-9-]{3,48}$")
HW_ID_RE = re.compile(r"^[0-9a-f]{4,32}$")
RESERVED_IDS = {"provision"}

BACKEND_SUBSCRIPTIONS = (
    f"{PREFIX}/provision/+/request",
    f"{PREFIX}/+/{STATUS}",
    f"{PREFIX}/+/{META}",
    f"{PREFIX}/+/{TELEMETRY}",
    f"{PREFIX}/+/{RESP}",
)

# Error codes carried in resp.data.error.code
ERR_UNKNOWN_COMMAND = "unknown_command"
ERR_BAD_ARGS = "bad_args"
ERR_SENSOR_NOT_FOUND = "sensor_not_found"
ERR_SENSOR_ERROR = "sensor_error"
ERR_INTERNAL = "internal"


class ProtocolError(ValueError):
    """Payload or topic that does not follow protocol v1."""


def is_valid_device_id(device_id: str) -> bool:
    return bool(DEVICE_ID_RE.match(device_id)) and device_id not in RESERVED_IDS


def is_valid_hw_id(hw_id: str) -> bool:
    return bool(HW_ID_RE.match(hw_id))


def default_device_id(hw_id: str) -> str:
    return f"esp32-{hw_id}"


def device_topic(device_id: str, leaf: str) -> str:
    return f"{PREFIX}/{device_id}/{leaf}"


def provision_request_topic(hw_id: str) -> str:
    return f"{PREFIX}/provision/{hw_id}/request"


def provision_response_topic(hw_id: str) -> str:
    return f"{PREFIX}/provision/{hw_id}/response"


@dataclass(frozen=True)
class TopicInfo:
    """Parsed incoming topic: kind is a message type, key is device_id or hw_id."""

    kind: str
    key: str


def parse_topic(topic: str) -> TopicInfo | None:
    """Return what an incoming topic means for the backend, or None if it is not ours."""
    parts = topic.split("/")
    if len(parts) == 5 and parts[:3] == ["iot", "v1", "provision"] and parts[4] == "request":
        return TopicInfo(PROVISION_REQUEST, parts[3]) if is_valid_hw_id(parts[3]) else None
    if len(parts) == 4 and parts[:2] == ["iot", "v1"] and parts[3] in DEVICE_LEAVES:
        return TopicInfo(parts[3], parts[2]) if is_valid_device_id(parts[2]) else None
    return None


@dataclass
class Envelope:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: float | None = field(default_factory=time.time)
    v: int = VERSION

    def encode(self) -> bytes:
        raw = json.dumps(
            {"v": self.v, "id": self.id, "ts": self.ts, "type": self.type, "data": self.data},
            separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
        if len(raw) > MAX_PAYLOAD:
            raise ProtocolError(f"payload {len(raw)} bytes exceeds {MAX_PAYLOAD}")
        return raw

    @classmethod
    def decode(cls, payload: bytes, expected_type: str | None = None) -> Envelope:
        if len(payload) > MAX_PAYLOAD:
            raise ProtocolError(f"payload {len(payload)} bytes exceeds {MAX_PAYLOAD}")
        try:
            obj = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolError(f"invalid JSON: {exc}") from exc
        if not isinstance(obj, dict):
            raise ProtocolError("envelope must be a JSON object")
        if obj.get("v") != VERSION:
            raise ProtocolError(f"unsupported protocol version {obj.get('v')!r}")
        msg_type, msg_id, data, ts = obj.get("type"), obj.get("id"), obj.get("data"), obj.get("ts")
        if not isinstance(msg_type, str) or not isinstance(msg_id, str) or not msg_id:
            raise ProtocolError("envelope needs string 'type' and 'id'")
        if not isinstance(data, dict):
            raise ProtocolError("envelope 'data' must be an object")
        if ts is not None and (isinstance(ts, bool) or not isinstance(ts, (int, float))):
            raise ProtocolError("envelope 'ts' must be a number or null")
        if expected_type is not None and msg_type != expected_type:
            raise ProtocolError(f"expected type {expected_type!r}, got {msg_type!r}")
        return cls(type=msg_type, data=data, id=msg_id, ts=None if ts is None else float(ts))


def command(name: str, args: dict[str, Any] | None = None, ttl_s: int = 30) -> Envelope:
    return Envelope(CMD, {"name": name, "args": args or {}, "ttl_s": ttl_s})


def provision_response(status: str, device_id: str | None = None, reason: str | None = None) -> Envelope:
    data: dict[str, Any] = {"status": status}
    if device_id is not None:
        data["device_id"] = device_id
    if reason is not None:
        data["reason"] = reason
    return Envelope(PROVISION_RESPONSE, data)
