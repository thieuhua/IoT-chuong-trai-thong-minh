import json
import pytest
import commands
import app
from core import protocol as p
from core import session
from sensors.base import Sensor, SensorError
from umqtt.simple import MQTTClient


def invoke(ctx, name, args=None, ts=None, ttl=30):
    payload = p.encode(p.CMD, {"name": name, "args": args if args is not None else {}, "ttl_s": ttl}, "cmd-1", ts)
    commands.dispatch(ctx, payload)
    return [json.loads(item[1])["data"] for item in ctx.link.client.publishes
            if item[0].endswith(b"/resp")][-1]


def test_ping_and_info(ctx):
    assert invoke(ctx, "ping") == {"re": "cmd-1", "ok": True, "result": {"uptime_s": 0}}
    result = invoke(ctx, "get_info")["result"]
    assert result["fw"] == app.FW_VERSION
    assert result["hw_id"] == ctx.identity.hw_id
    assert result["ip"] == "192.0.2.10" and result["rssi"] == -45
    assert result["mem_free"] > 0
    assert result["ota"] == "ok"
    assert ctx.meta()["ota"] == "ok"
    assert result["commands"] == ["ping", "get_info", "read", "set_interval",
                                  "servo_set", "servo_sequence", "ota_begin", "ota_chunk",
                                  "ota_commit", "ota_abort", "ota_status", "reboot"]


def test_read_all_and_one(ctx):
    result = invoke(ctx, "read")["result"]
    assert "sim" in result["readings"] and "errors" not in result
    assert invoke(ctx, "read", {"sensor": "sim"})["result"] == result


def test_read_failures(ctx):
    class Broken(Sensor):
        def _measure(self):
            raise OSError("sensor timeout")
    ctx.sensors.append(Broken({"name": "broken"}))
    result = invoke(ctx, "read")["result"]
    assert result["errors"] == {"broken": "sensor timeout"}
    assert "sim" in result["readings"]
    assert invoke(ctx, "read", {"sensor": "broken"})["error"]["code"] == p.ERR_SENSOR_ERROR
    assert invoke(ctx, "read", {"sensor": "missing"})["error"]["code"] == p.ERR_SENSOR_NOT_FOUND


@pytest.mark.parametrize("seconds", [1, 10, 3600])
def test_set_interval_persists_and_defers_meta(ctx, seconds):
    assert invoke(ctx, "set_interval", {"seconds": seconds})["result"] == {"interval_s": seconds}
    with open(ctx.identity.state_path) as stream:
        assert json.load(stream)["interval_s"] == seconds
    # Inside the umqtt callback only the QoS 0 resp goes out; the session loop publishes meta.
    assert ctx.meta_dirty is True
    assert [msg[0].rsplit(b"/", 1)[-1] for msg in ctx.link.client.publishes] == [b"resp"]
    ctx.meta_dirty = False
    ctx.publish_meta()
    meta = ctx.link.client.publishes[-1]
    assert meta[0].endswith(b"/meta") and meta[2:] == (True, 1)
    assert json.loads(meta[1])["data"]["interval_s"] == seconds


@pytest.mark.parametrize("name,args", [("ping", {"extra": 1}), ("get_info", {"extra": 1}),
    ("reboot", {"extra": 1}), ("read", {"sensor": None}), ("read", {"sensor": 12}),
    ("set_interval", {}), ("set_interval", {"seconds": 0}), ("set_interval", {"seconds": 3601}),
    ("set_interval", {"seconds": True}), ("set_interval", {"seconds": 1.5}),
    ("set_interval", {"seconds": "10"}), ("ping", []), ([], {})])
def test_bad_args(ctx, name, args):
    assert invoke(ctx, name, args)["error"]["code"] == p.ERR_BAD_ARGS


def test_unknown_and_internal(ctx, monkeypatch):
    assert invoke(ctx, "nope")["error"]["code"] == p.ERR_UNKNOWN_COMMAND
    def broken(ctx, args):
        raise OSError("failed storage")
    monkeypatch.setitem(commands.REGISTRY, "broken", broken)
    assert invoke(ctx, "broken")["error"]["code"] == p.ERR_INTERNAL


def test_ttl_and_malformed_drop(ctx, monkeypatch):
    monkeypatch.setattr(ctx.clock, "now", lambda: 100)
    commands.dispatch(ctx, p.encode(p.CMD, {"name": "ping", "ttl_s": 10}, "old", 89))
    assert not ctx.link.client.publishes
    commands.dispatch(ctx, b"garbage")
    commands.dispatch(ctx, p.encode(p.META, {}, "wrong"))
    assert not ctx.link.client.publishes
    assert invoke(ctx, "ping", ts=90, ttl=10)["ok"]
    monkeypatch.setattr(ctx.clock, "now", lambda: None)
    assert invoke(ctx, "ping", ts=0, ttl=0)["ok"]
    assert invoke(ctx, "ping", ttl=-1)["error"]["code"] == p.ERR_BAD_ARGS


def test_reboot_response_offline_close_reset(ctx, monkeypatch):
    import machine
    MQTTClient.next_messages = [(b"iot/v1/esp32-test/cmd", p.encode(p.CMD, {"name": "reboot"}, "r"))]
    def reset():
        client = MQTTClient.instances[-1]
        assert client.sock.closed
        events = client.events
        resp_idx = next(i for i, e in enumerate(events) if e[0] == "publish" and e[1].endswith(b"/resp"))
        offline_idx = next(i for i, e in enumerate(events) if e[0] == "publish" and
                           json.loads(e[2])["data"].get("reason") == "reboot")
        assert resp_idx < offline_idx
        assert json.loads(events[resp_idx][2])["data"] == {"re": "r", "ok": True, "result": {}}
        assert events[offline_idx][3:] == (True, 1)
        assert events[-1][0] == "disconnect"
    monkeypatch.setattr(machine, "reset", reset)
    session.run(ctx)


def test_failed_reboot_response_does_not_schedule_reset(ctx, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("connection lost")
    monkeypatch.setattr(ctx, "publish", fail)
    with pytest.raises(OSError):
        commands.dispatch(ctx, p.encode(p.CMD, {"name": "reboot"}, "r"))
    assert not ctx.reboot_requested
