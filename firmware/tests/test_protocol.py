import importlib.util
import json
from pathlib import Path
import sys
import pytest
from core import protocol as p


@pytest.fixture(scope="module")
def backend():
    path = Path(__file__).resolve().parents[2] / "backend" / "iot_core" / "protocol.py"
    spec = importlib.util.spec_from_file_location("backend_protocol_contract", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_backend_constants_and_topics(backend):
    for name in dir(backend):
        if name.isupper() and not name.endswith("_RE"):
            assert getattr(p, name) == getattr(backend, name), name
    for leaf in (p.STATUS, p.META, p.TELEMETRY, p.CMD, p.RESP):
        assert p.device_topic("esp32-test", leaf) == backend.device_topic("esp32-test", leaf)
    for name in ("provision_request_topic", "provision_response_topic", "default_device_id"):
        assert getattr(p, name)("a0b1c2d3e4f5") == getattr(backend, name)("a0b1c2d3e4f5")


def test_envelopes_interoperate(backend):
    data = {"sensors": [{"fields": {"temperature": "\u00b0C"}}]}
    raw = p.encode(p.META, data, "2-1", None)
    decoded = backend.Envelope.decode(raw)
    assert decoded.id == "2-1" and decoded.ts is None and decoded.data == data
    back = backend.Envelope(p.CMD, {"name": "ping"}, id="abc", ts=123).encode()
    assert p.decode(back, p.CMD) == json.loads(back)


@pytest.mark.parametrize("payload", [b"broken", b"[]", b'{}', b'\xff', b"x" * 4097])
def test_bad_envelopes(payload):
    with pytest.raises(p.ProtocolError):
        p.decode(payload)


@pytest.mark.parametrize("field,value", [("v", 2), ("v", True), ("id", ""), ("id", 3),
                                         ("type", None), ("data", []), ("ts", True),
                                         ("ts", "today"), ("ts", float("inf"))])
def test_bad_fields(field, value):
    obj = {"v": 1, "id": "x", "type": p.CMD, "data": {}, "ts": None}
    obj[field] = value
    with pytest.raises(p.ProtocolError):
        p.decode(json.dumps(obj).encode())


def test_size_type_and_id_validation():
    with pytest.raises(p.ProtocolError):
        p.encode(p.META, {"huge": "x" * 4096}, "x")
    with pytest.raises(p.ProtocolError):
        p.decode(p.encode(p.META, {}, "x"), p.CMD)
    assert p.is_valid_device_id("esp32-a0b1")
    assert not p.is_valid_device_id("provision")
    assert not p.is_valid_device_id("bad/+id")
    assert p.is_valid_hw_id("a0b1")
    assert not p.is_valid_hw_id("A0B1")
