import dht
import time
from machine import Pin
from sensors.base import Sensor


class DHT11(Sensor):
    driver = "dht11"
    fields = {"temperature": "\u00b0C", "humidity": "%"}
    min_interval_ms = 2000
    device_class = dht.DHT11

    def __init__(self, cfg):
        super().__init__(cfg)
        self.device = self.device_class(Pin(cfg.get("pin", 23), Pin.IN, Pin.PULL_UP))
        self._ready_at = time.ticks_ms()

    def _measure(self):
        # First sampling is deferred until the sensor has stabilised after boot.
        if self._ready_at is not None:
            if time.ticks_diff(time.ticks_ms(), self._ready_at) < self.min_interval_ms:
                raise OSError("sensor warming up")
            self._ready_at = None  # warm-up done; avoid ticks_ms wrap-around later
        self.device.measure()
        return {"temperature": self.device.temperature(), "humidity": self.device.humidity()}


class DHT22(DHT11):
    driver = "dht22"
    device_class = dht.DHT22
