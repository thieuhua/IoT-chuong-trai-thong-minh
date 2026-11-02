import time


class SensorError(Exception):
    pass


class Sensor:
    driver = "base"
    fields = {}
    min_interval_ms = 0

    def __init__(self, cfg):
        self.name = cfg["name"]
        self._cached = None
        self._measured_at = None

    def meta(self):
        return {"name": self.name, "driver": self.driver, "fields": self.fields}

    def read(self):
        now = time.ticks_ms()
        # 0 <= diff guards against ticks_ms wrap-around after very long idle periods.
        if (self._cached is not None and
                0 <= time.ticks_diff(now, self._measured_at) < self.min_interval_ms):
            return dict(self._cached)
        try:
            value = self._measure()
            if not isinstance(value, dict):
                raise SensorError("sensor returned invalid readings")
        except Exception as exc:
            raise SensorError(str(exc))
        self._cached = dict(value)
        self._measured_at = time.ticks_ms()
        return dict(value)

    def _measure(self):
        raise NotImplementedError()
