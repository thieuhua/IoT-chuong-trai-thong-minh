import gc
import importlib.util
import os
from pathlib import Path
import sys
import time
import pytest

FIRMWARE = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(FIRMWARE / "tests" / "stubs"), str(FIRMWARE / "src")]


@pytest.fixture(autouse=True)
def board_environment(monkeypatch, tmp_path):
    # Every host write, including pytest temp files, stays inside firmware/tests/.
    import main
    from core import ota
    for module in (main, ota):
        for constant, filename in (("APP_DIR", "app"), ("NEW_DIR", "app_new"),
                                   ("OLD_DIR", "app_old"), ("OTA_FILE", "ota.json"),
                                   ("CONFIG", "config.json"), ("CONFIG_FILE", "config.json"),
                                   ("CONFIG_OLD", "config.json.old")):
            if hasattr(module, constant):
                monkeypatch.setattr(module, constant, (tmp_path / filename).as_posix())
    monkeypatch.setattr(os, "rename", os.replace)
    # statvfs is absent on Windows; use deterministic available flash in host tests.
    monkeypatch.setattr(os, "statvfs", lambda path: (4096, 4096, 10000, 10000), raising=False)
    if os.name == "nt":
        # Board _mkdirs walks POSIX roots; Windows drive-letter paths need native parents.
        monkeypatch.setattr(ota, "_mkdirs", lambda path: Path(path).parent.mkdir(parents=True, exist_ok=True))
    elapsed = [0]
    monkeypatch.setattr(time, "ticks_ms", lambda: elapsed[0] % (1 << 30), raising=False)
    monkeypatch.setattr(time, "ticks_add", lambda ticks, delta: (ticks + delta) % (1 << 30),
                        raising=False)
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
def loader(board_environment, monkeypatch):
    import main
    spec = importlib.util.spec_from_file_location("_ota_test_loader", FIRMWARE / "src" / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("APP_DIR", "NEW_DIR", "OLD_DIR", "OTA_FILE", "CONFIG", "CONFIG_OLD"):
        monkeypatch.setattr(module, name, getattr(main, name))
    return module


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
