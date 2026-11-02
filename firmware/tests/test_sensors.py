import sys
import pytest
from sensors import build_sensors
from sensors.base import Sensor, SensorError


def test_build_and_cache(board_environment):
    sensors = build_sensors([{"name": "room", "driver": "dht11", "pin": 23},
                             {"name": "outside", "driver": "dht22", "pin": 22},
                             {"name": "soil", "driver": "adc", "pin": 34, "atten": "11db"},
                             {"name": "sim", "driver": "simulated"}])
    room, outside, soil, sim = sensors
    with pytest.raises(SensorError, match="warming up"):
        room.read()
    board_environment[0] += 2000
    assert room.read() == {"temperature": 25, "humidity": 60}
    assert room.device.pin.pin == 23 and room.device.pin.pin != outside.device.pin.pin
    value = room.read()
    value["temperature"] = -999
    assert room.read()["temperature"] == 25
    assert room.device.measures == 1
    board_environment[0] += 2000
    room.read()
    assert room.device.measures == 2
    assert outside.meta()["driver"] == "dht22"
    assert soil.read() == {"raw": 32768, "voltage": 1.65}
    assert sim.read() == sim.read()
    assert room.meta()["fields"] == {"temperature": "\u00b0C", "humidity": "%"}


def test_lazy_import(monkeypatch):
    # Verify the factory requests only the configured module, even if already loaded.
    import builtins
    original = builtins.__import__
    seen = []
    def record(name, *args, **kwargs):
        seen.append(name)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", record)
    build_sensors([{"name": "sim", "driver": "simulated"}])
    assert "sensors.simulated" in seen
    assert "sensors.dht" not in seen and "sensors.analog" not in seen


@pytest.mark.parametrize("config", [[{"name": "x", "driver": "unknown"}],
    [{"name": "", "driver": "simulated"}],
    [{"name": "x", "driver": "simulated"}, {"name": "x", "driver": "adc"}]])
def test_bad_sensor_config(config):
    with pytest.raises(ValueError):
        build_sensors(config)


def test_cache_ticks_wrap(board_environment):
    class Counting(Sensor):
        min_interval_ms = 2000
        calls = 0
        def _measure(self):
            self.calls += 1
            return {"count": self.calls}
    board_environment[0] = (1 << 30) - 500
    sensor = Counting({"name": "counter"})
    assert sensor.read() == {"count": 1}
    board_environment[0] += 1000
    assert sensor.read() == {"count": 1}
    board_environment[0] += 1000
    assert sensor.read() == {"count": 2}
