"""MQTT v1 wire contract. Keep constants aligned with backend/iot_core/protocol.py."""
import json
import gc

VERSION = 1
PREFIX = "iot/v1"
MAX_PAYLOAD = 4096
PROVISION_REQUEST = "provision.request"
PROVISION_RESPONSE = "provision.response"
STATUS = "status"
META = "meta"
TELEMETRY = "telemetry"
CMD = "cmd"
RESP = "resp"
DEVICE_LEAVES = (STATUS, META, TELEMETRY, RESP)
RESERVED_IDS = {"provision"}
BACKEND_SUBSCRIPTIONS = (
    PREFIX + "/provision/+/request",
    PREFIX + "/+/status", PREFIX + "/+/meta",
    PREFIX + "/+/telemetry", PREFIX + "/+/resp",
)
ERR_UNKNOWN_COMMAND = "unknown_command"
ERR_BAD_ARGS = "bad_args"
ERR_SENSOR_NOT_FOUND = "sensor_not_found"
ERR_SENSOR_ERROR = "sensor_error"
ERR_INTERNAL = "internal"
ERR_ACTUATOR_NOT_FOUND = "actuator_not_found"
ERR_OTA = "ota_error"


class ProtocolError(ValueError):
    pass


def is_valid_device_id(value):
    return (isinstance(value, str) and 3 <= len(value) <= 48
            and value not in RESERVED_IDS
            and all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in value))


def is_valid_hw_id(value):
    return (isinstance(value, str) and 4 <= len(value) <= 32
            and all(c in "0123456789abcdef" for c in value))


def default_device_id(hw_id):
    return "esp32-" + hw_id


def device_topic(device_id, leaf):
    return PREFIX + "/" + device_id + "/" + leaf


def provision_request_topic(hw_id):
    return PREFIX + "/provision/" + hw_id + "/request"


def provision_response_topic(hw_id):
    return PREFIX + "/provision/" + hw_id + "/response"


def _finite(value):
    return value == value and value != float("inf") and value != -float("inf")


def _validate(obj, expected_type=None):
    if not isinstance(obj, dict):
        raise ProtocolError("envelope must be an object")
    if type(obj.get("v")) is not int or obj["v"] != VERSION:
        raise ProtocolError("unsupported protocol version")
    if not isinstance(obj.get("id"), str) or not obj["id"]:
        raise ProtocolError("envelope needs string id")
    if not isinstance(obj.get("type"), str) or not isinstance(obj.get("data"), dict):
        raise ProtocolError("invalid type or data")
    if "ts" not in obj:
        raise ProtocolError("missing ts")
    ts = obj["ts"]
    if ts is not None and (type(ts) not in (int, float) or not _finite(ts)):
        raise ProtocolError("ts must be finite number or null")
    if expected_type is not None and obj["type"] != expected_type:
        raise ProtocolError("unexpected message type")
    return obj


def encode(msg_type, data, msg_id, ts=None):
    obj = _validate({"v": VERSION, "id": msg_id, "ts": ts,
                     "type": msg_type, "data": data})
    raw = json.dumps(obj).encode("utf-8")
    if len(raw) > MAX_PAYLOAD:
        raise ProtocolError("payload exceeds 4096 bytes")
    return raw


def decode(payload, expected_type=None):
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError("payload exceeds 4096 bytes")
    try:
        obj = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeError, TypeError) as exc:
        raise ProtocolError("invalid JSON: " + str(exc))
    finally:
        gc.collect()
    return _validate(obj, expected_type)
