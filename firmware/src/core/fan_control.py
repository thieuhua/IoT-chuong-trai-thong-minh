"""Cooperative temperature controller; never read a sensor in a timer callback."""
import time
from sensors.base import SensorError
from core.protocol import _finite


class FanControl:
    def __init__(self, sensor, relay, config):
        self.sensor = sensor
        self.relay = relay
        self.on_c = config.get("on_c", 32)
        self.off_c = config.get("off_c", 30)
        self.fault_reads = config.get("fault_reads", 3)
        self.ttl_ms = int(config.get("manual_ttl_min", 30) * 60000)
        if (self.off_c >= self.on_c or type(self.fault_reads) is not int
                or self.fault_reads < 1 or not 0 < self.ttl_ms < (1 << 29)):
            raise ValueError("invalid fan_control thresholds or manual TTL")
        self.period_ms = max(2000, sensor.min_interval_ms)
        self.mode = "AUTO"
        self.sensor_ok = False
        self.failures = 0
        self.temperature = None
        self.sample = None
        self.error = None
        self._last_read = None
        self._manual_at = None

    @property
    def fault(self):
        return self.failures >= self.fault_reads

    def status(self):
        return {"mode": self.mode, "fan_on": self.relay.on, "sensor_ok": self.sensor_ok}

    def manual(self):
        self.mode = "MANUAL"
        self._manual_at = time.ticks_ms()

    def set_mode(self, mode):
        if mode == "manual":
            self.manual()
        else:
            self.mode = "AUTO"
            self._manual_at = None
        self._apply()

    def _apply(self):
        self.relay.force_on(self.fault)
        if self.fault:
            return
        if self.mode == "AUTO" and self.sensor_ok:
            if (self.temperature >= self.on_c
                    and (not self.relay.on or self.relay._off_at is not None)):
                self.relay.set(True)
            elif self.temperature <= self.off_c and self.relay.on:
                self.relay.set(False)

    def observe(self, sample=None, error=None):
        """Consume one fresh sample, from the poller or a local telemetry producer."""
        temperature = sample.get("temperature") if isinstance(sample, dict) else None
        if error is None and (type(temperature) not in (int, float) or not _finite(temperature)):
            error = "invalid temperature"
        self.sample, self.error = (sample, None) if error is None else (None, str(error))
        self.sensor_ok = error is None
        if self.sensor_ok:
            self.temperature = temperature
            self.failures = 0
        else:
            self.failures = min(self.failures + 1, self.fault_reads)
        self._last_read = time.ticks_ms()
        self._apply()

    def tick(self):
        now = time.ticks_ms()
        if (self.mode == "MANUAL"
                and time.ticks_diff(now, self._manual_at) >= self.ttl_ms):
            self.mode = "AUTO"
            self._manual_at = None
        if self._last_read is None or time.ticks_diff(now, self._last_read) >= self.period_ms:
            # Reserve before reading: cooperative feed() calls cannot recursively sample.
            self._last_read = now
            try:
                sample = self.sensor.read()
            except SensorError as exc:
                self.observe(error=exc)
            else:
                self.observe(sample)
        self._apply()
