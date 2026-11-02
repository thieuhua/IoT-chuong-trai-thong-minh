import random
from sensors.base import Sensor


class Simulated(Sensor):
    driver = "simulated"
    fields = {"temperature": "\u00b0C", "humidity": "%"}
    min_interval_ms = 500

    def __init__(self, cfg):
        super().__init__(cfg)
        self.temperature = 25.0
        self.humidity = 60.0

    def _measure(self):
        self.temperature = max(-10, min(50, self.temperature + (random.getrandbits(8) / 255 - 0.5)))
        self.humidity = max(0, min(100, self.humidity + (random.getrandbits(8) / 255 - 0.5)))
        return {"temperature": round(self.temperature, 2), "humidity": round(self.humidity, 2)}
