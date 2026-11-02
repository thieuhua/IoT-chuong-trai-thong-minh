import json
import os
from pathlib import Path
import time
import pytest
from core.clock import Clock
from core.identity import Identity
from core import storage, wifi
from core.runtime import pause


def test_identity_password_boot_sequence_and_interval(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.os, "rename", os.replace)
    state = str(tmp_path / "state.json")
    device = str(tmp_path / "device.json")
    first = Identity(state, device)
    assert first.hw_id == "a0b1c2d3e4f5"
    assert first.next_id() == "1-1" and first.next_id() == "1-2"
    password = first.device["password"]
    assert len(password) == 32 and int(password, 16) >= 0
    first.approve("esp32-device")
    first.set_interval(12)
    second = Identity(state, device)
    assert second.next_id() == "2-1"
    assert second.device == {"device_id": "esp32-device", "password": password}
    assert second.state["interval_s"] == 12
    from app import App
    assert App({"sensors": [], "interval_s": 99}, second).interval_s == 12


def test_atomic_write_failure_preserves_old_file(tmp_path, monkeypatch):
    path = str(tmp_path / "settings.json")
    Path(path).write_text('{"old": true}')
    def fail(source, destination):
        assert Path(source).is_file() and destination == path
        raise OSError("rename failed")
    monkeypatch.setattr(storage.os, "rename", fail)
    with pytest.raises(OSError):
        storage.save_json(path, {"new": True})
    assert storage.load_json(path, {}) == {"old": True}
    assert storage.load_json(str(tmp_path / "missing"), {"default": 1}) == {"default": 1}
    Path(path).write_text("corrupt")
    assert storage.load_json(path, None) is None


def test_clock_epoch_and_sync_failure(monkeypatch):
    import ntptime
    monkeypatch.setattr(time, "gmtime", lambda n: (2000,))
    monkeypatch.setattr(time, "time", lambda: 100)
    clock = Clock()
    assert clock.now() is None
    assert clock.sync()
    assert ntptime.timeout == 2
    assert clock.now() == 946684900.0
    monkeypatch.setattr(time, "gmtime", lambda n: (1970,))
    assert Clock().epoch_offset == 0
    monkeypatch.setattr(ntptime, "failure", OSError("NTP down"))
    unsynced = Clock()
    assert not unsynced.sync() and unsynced.now() is None


def test_wifi_timeout_and_watchdog_waits(monkeypatch, board_environment):
    wlan = wifi.interface()
    wlan.connected = False
    monkeypatch.setattr(wlan, "connect", lambda s, p: None)
    feeds = []
    with pytest.raises(OSError, match="timeout"):
        wifi.connect("ssid", "pw", timeout_s=1, feed=lambda: feeds.append(1))
    assert board_environment[0] >= 1000 and len(feeds) >= 20
    before = len(feeds)
    pause(2, lambda: feeds.append(1))
    assert len(feeds) - before >= 40


def test_watchdog_during_recovery(ctx, monkeypatch):
    import machine
    from core import provisioning, session
    from app import App
    app = App(dict(ctx.config, watchdog_s=10), ctx.identity)
    assert app.watchdog.timeout == 10000
    failures = [0]
    sleeps = []
    def fail(ctx):
        failures[0] += 1
        if failures[0] == 7:
            raise KeyboardInterrupt()
        raise OSError("broker down")
    monkeypatch.setattr(session, "run", fail)
    import app as app_module
    original_pause = app_module.pause
    def record_pause(seconds, feed):
        sleeps.append(seconds)
        original_pause(seconds, feed)
    monkeypatch.setattr(app_module, "pause", record_pause)
    with pytest.raises(KeyboardInterrupt):
        app.run()
    assert sleeps == [2, 4, 8, 16, 30, 30]
    assert app.watchdog.feeds > 100


def test_watchdog_during_provisioning(ctx):
    import machine
    from core import provisioning, protocol as p
    from umqtt.simple import MQTTClient
    ctx.watchdog = machine.WDT(timeout=10000)
    ctx.identity.approve(None)
    topic = p.provision_response_topic(ctx.identity.hw_id).encode()
    MQTTClient.next_messages = [(topic, p.encode(p.PROVISION_RESPONSE, {"status": "pending"}, "p")),
        (topic, p.encode(p.PROVISION_RESPONSE, {"status": "approved", "device_id": "esp32-approved"}, "a"))]
    provisioning.run(ctx)
    assert ctx.watchdog.feeds >= 3
