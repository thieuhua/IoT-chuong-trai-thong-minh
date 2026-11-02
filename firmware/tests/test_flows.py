import json
from pathlib import Path
import pytest
from core import provisioning, session, protocol as p
from core.mqtt_link import MQTTLink, NotAuthorised
from umqtt.simple import MQTTClient, MQTTException


def provision_response(ctx, status, **extra):
    return (p.provision_response_topic(ctx.identity.hw_id).encode(),
            p.encode(p.PROVISION_RESPONSE, dict(status=status, **extra), "backend"))


def test_pending_approved(ctx, capsys):
    ctx.identity.approve(None)
    password = ctx.identity.device["password"]
    MQTTClient.next_messages = [provision_response(ctx, "pending"),
                               provision_response(ctx, "approved", device_id="esp32-approved")]
    provisioning.run(ctx)
    client = MQTTClient.instances[-1]
    assert client.will is None
    assert client.user == b"bootstrap" and client.client_id == ctx.identity.hw_id.encode()
    assert client.subscriptions == [(p.provision_response_topic(ctx.identity.hw_id).encode(), 1)]
    raw = client.publishes[0]
    assert raw[0] == p.provision_request_topic(ctx.identity.hw_id).encode()
    assert raw[2:] == (False, 0)
    data = p.decode(raw[1], p.PROVISION_REQUEST)["data"]
    assert data["password"] == password and data["hw_id"] == ctx.identity.hw_id
    assert data["model"] == "esp32" and data["fw"] == "0.1.0"
    assert "sensors" in data and "commands" in data and "interval_s" not in data
    assert json.loads(Path(ctx.identity.device_path).read_text())["device_id"] == "esp32-approved"
    assert ctx.identity.device["password"] == password
    assert client.sock.closed
    assert "waiting for approval, hw_id=" + ctx.identity.hw_id in capsys.readouterr().out


def test_rejected_waits_60_seconds_and_keeps_polling(ctx, board_environment, monkeypatch, capsys):
    ctx.identity.approve(None)
    MQTTClient.next_messages = [provision_response(ctx, "rejected", reason="admin denied")]
    original = MQTTClient.publish
    sent_at = []
    def publish(client, topic, payload, retain=False, qos=0):
        sent_at.append(board_environment[0])
        original(client, topic, payload, retain, qos)
        if len(sent_at) == 2:
            client.inject(*provision_response(ctx, "approved", device_id="esp32-approved"))
    monkeypatch.setattr(MQTTClient, "publish", publish)
    provisioning.run(ctx)
    assert len(sent_at) == 2 and sent_at[1] - sent_at[0] >= 60000
    assert any(e[0] == "ping" for e in MQTTClient.instances[-1].events)
    assert "admin denied" in capsys.readouterr().out


def test_provision_retry_and_ignore_invalid(ctx, board_environment, monkeypatch):
    ctx.identity.approve(None)
    MQTTClient.next_messages = [(p.provision_response_topic(ctx.identity.hw_id).encode(), b"bad"),
        (p.provision_response_topic(ctx.identity.hw_id).encode(), p.encode(p.META, {}, "wrong")),
        provision_response(ctx, "approved", device_id="provision")]
    original = MQTTClient.publish
    requests = []
    def publish(client, topic, payload, retain=False, qos=0):
        requests.append((board_environment[0], json.loads(payload)))
        original(client, topic, payload, retain, qos)
        if len(requests) == 2:
            client.inject(*provision_response(ctx, "approved", device_id="esp32-approved"))
    monkeypatch.setattr(MQTTClient, "publish", publish)
    provisioning.run(ctx)
    assert requests[1][0] - requests[0][0] >= 10000
    assert requests[0][1]["data"]["password"] == requests[1][1]["data"]["password"]
    assert requests[0][1]["id"] != requests[1][1]["id"]


def test_session_connection_order_lwt_and_telemetry(ctx, monkeypatch, board_environment):
    polls = [0]
    original = MQTTClient.check_msg
    def poll(client):
        original(client)
        polls[0] += 1
        if polls[0] > 205:
            raise OSError("link lost")
    monkeypatch.setattr(MQTTClient, "check_msg", poll)
    with pytest.raises(OSError, match="link lost"):
        session.run(ctx)
    client = MQTTClient.instances[-1]
    assert client.client_id == client.user == b"esp32-test"
    assert client.password == ctx.identity.device["password"].encode()
    assert [e[0] for e in client.events[:5]] == ["will", "connect", "publish", "publish", "subscribe"]
    assert client.will[0] == b"iot/v1/esp32-test/status" and client.will[2:] == (True, 1)
    assert p.decode(client.will[1], p.STATUS)["data"] == {"state": "offline", "reason": "lwt"}
    online, meta, telemetry = client.publishes
    assert online[2:] == meta[2:] == (True, 1)
    assert p.decode(online[1], p.STATUS)["data"] == {"state": "online"}
    assert p.decode(meta[1], p.META)["data"] == ctx.meta()
    assert telemetry[2:] == (False, 0)
    assert "sim" in p.decode(telemetry[1], p.TELEMETRY)["data"]["readings"]
    assert client.subscriptions == [(b"iot/v1/esp32-test/cmd", 1)]
    assert client.sock.closed and ctx.link is None
    assert not any(e[0] == "disconnect" for e in client.events)


@pytest.mark.parametrize("code", [4, 5])
def test_session_not_authorised_clears_credentials(ctx, code):
    # A single refusal may be a broker hiccup: keep the identity and let the app back off.
    for _ in range(session.AUTH_FAILURES_BEFORE_REVOKE - 1):
        MQTTClient.next_connect_error = MQTTException(code)
        with pytest.raises(NotAuthorised):
            session.run(ctx)
        assert ctx.identity.device["device_id"]
    MQTTClient.next_connect_error = MQTTException(code)
    session.run(ctx)
    assert ctx.identity.device is None
    assert not Path(ctx.identity.device_path).exists()
    assert MQTTClient.instances[-1].sock.closed
    new = ctx.identity.load_device()
    assert new["device_id"] is None and len(new["password"]) == 32


def test_session_keyboard_interrupt_offline(ctx):
    MQTTClient.next_messages = [KeyboardInterrupt()]
    with pytest.raises(KeyboardInterrupt):
        session.run(ctx)
    client = MQTTClient.instances[-1]
    assert p.decode(client.publishes[-1][1], p.STATUS)["data"] == {"state": "offline", "reason": "shutdown"}
    assert client.publishes[-1][2:] == (True, 1)
    assert client.events[-1] == ("disconnect",)


def test_mqtt_ping_outgoing_timer_dispatch_and_close(board_environment):
    received = []
    link = MQTTLink("test", "localhost", keepalive=30, handler=lambda t, b: received.append((t, b)))
    link.connect()
    board_environment[0] += 14999
    link.poll()
    assert not any(e[0] == "ping" for e in link.client.events)
    link.publish("topic", b"payload")
    board_environment[0] += 1
    link.poll()
    assert not any(e[0] == "ping" for e in link.client.events)
    board_environment[0] += 14999
    link.poll()
    assert link.client.events[-1] == ("ping",)
    link.client.inject(b"topic", b"data")
    link.poll()
    assert received == [("topic", b"data")]
    link.close()
    link.close()
    assert link.client.events.count(("disconnect",)) == 1


def test_mqtt_oserror_propagates_and_bootstrap_auth_maps():
    MQTTClient.next_connect_error = OSError("network")
    link = MQTTLink("test", "localhost")
    with pytest.raises(OSError):
        link.connect()
    link.close()
    MQTTClient.next_connect_error = MQTTException(5)
    link = MQTTLink("test", "localhost")
    with pytest.raises(NotAuthorised):
        link.connect()
    link.close()
