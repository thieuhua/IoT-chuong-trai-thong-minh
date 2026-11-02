from machine import ADC, Pin
from sensors.base import Sensor


class Analog(Sensor):
    driver = "adc"
    fields = {"raw": "", "voltage": "V"}
    min_interval_ms = 50

    def __init__(self, cfg):
        super().__init__(cfg)
        self.adc = ADC(Pin(cfg.get("pin", 34)))
        levels = {"0db": ADC.ATTN_0DB, "2.5db": ADC.ATTN_2_5DB,
                  "6db": ADC.ATTN_6DB, "11db": ADC.ATTN_11DB}
        self.adc.atten(levels[cfg.get("atten", "11db")])

    def _measure(self):
        return {"raw": self.adc.read_u16(), "voltage": self.adc.read_uv() / 1000000}
