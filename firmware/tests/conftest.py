import gc
from pathlib import Path
import sys
import time
import pytest

FIRMWARE = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(FIRMWARE / "tests" / "stubs"), str(FIRMWARE / "src")]


@pytest.fixture(autouse=True)
def board_environment(monkeypatch):
    # Every host write, including pytest temp files, stays inside firmware/.
    elapsed = [0]
    monkeypatch.setattr(time, "ticks_ms", lambda: elapsed[0] % (1 << 30), raising=False)
    monkeypatch.setattr(time, "ticks_diff",
                        lambda a, b: ((a - b + (1 << 29)) % (1 << 30)) - (1 << 29), raising=False)
    monkeypatch.setattr(time, "sleep_ms", lambda ms: elapsed.__setitem__(0, elapsed[0] + ms), raising=False)
    monkeypatch.setattr(gc, "mem_free", lambda: 100000, raising=False)
    from umqtt.simple import MQTTClient
    MQTTClient.instances = []
    MQTTClient.next_messages = []
    MQTTClient.next_connect_error = None
    from core import wifi
    wifi._wlan = None
    import machine
    machine.reset_calls = 0
    yield elapsed


@pytest.fixture
def ctx(tmp_path):
    from app import App
    from core.identity import Identity
    # Windows rename does not replace existing destinations; emulate board POSIX rename.
    import os
    from core import storage
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(storage.os, "rename", os.replace)
        identity = Identity(str(tmp_path / "state.json"), str(tmp_path / "device.json"))
        identity.approve("esp32-test")
        app = App({"wifi": {"ssid": "test", "password": "test"},
                   "mqtt": {"host": "localhost", "bootstrap_password": "test"},
                   "ntp": False, "sensors": [{"driver": "simulated", "name": "sim"}]}, identity)
        from core.mqtt_link import MQTTLink
        app.link = MQTTLink("esp32-test", "localhost")
        yield app
