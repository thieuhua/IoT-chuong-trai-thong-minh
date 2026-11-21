"""Relay (or any on/off output) on a GPIO pin, with an optional automatic switch-off.

cfg: {"driver": "relay", "name": "relay", "pin": 25, "active_low": false, "initial": false,
      "max_on_ms": 0}

- active_low: many relay modules switch on when IN is pulled low; set true for those.
- initial: state applied at boot (default off).
- max_on_ms: safety limit; a relay left on longer than this is switched off (0 = no limit).
"""
import time
from machine import Pin

MAX_DURATION_MS = 86400000  # one day


def _duration_ms(value):
    if type(value) is not int or not 100 <= value <= MAX_DURATION_MS:
        raise ValueError("duration_ms must be an integer in 100.." + str(MAX_DURATION_MS))
    return value


class Relay:
    driver = "relay"

    def __init__(self, cfg):
        self.name = cfg["name"]
        self.pin = cfg["pin"]
        self.active_low = bool(cfg.get("active_low", False))
        max_on = cfg.get("max_on_ms", 0)
        self.max_on_ms = _duration_ms(max_on) if max_on else 0
        self.on = False
        self._forced_on = False
        self._off_at = None
        # Set the idle level before switching the pin to output, so the relay never blips on.
        self.output = Pin(self.pin, Pin.OUT, value=1 if self.active_low else 0)
        self.set(bool(cfg.get("initial", False)))

    def set(self, on, duration_ms=None):
        """Switch on/off. With duration_ms (only when switching on) it turns off by itself."""
        if type(on) is not bool:
            raise ValueError("on must be true or false")
        if duration_ms is not None:
            if not on:
                raise ValueError("duration_ms only applies when switching on")
            duration_ms = _duration_ms(duration_ms)
        if self._forced_on:
            if not on:
                raise ValueError("fan sensor fault: relay is forced on")
            duration_ms = None
        if (not self._forced_on and on and self.max_on_ms
                and (duration_ms is None or duration_ms > self.max_on_ms)):
            duration_ms = self.max_on_ms
        self._off_at = time.ticks_add(time.ticks_ms(), duration_ms) if on and duration_ms else None
        self.on = on
        self.output.value(1 if on != self.active_low else 0)

    def force_on(self, enabled):
        """Safety interlock takes precedence over both manual and timed switch-off."""
        self._forced_on = enabled
        if enabled and (not self.on or self._off_at is not None):
            self.set(True)

    def tick(self, now):
        """Called every few ms from a hardware timer: handles the automatic switch-off."""
        if self._off_at is not None and time.ticks_diff(now, self._off_at) >= 0:
            self.set(False)

    def state(self):
        result = {"on": self.on}
        if self._off_at is not None:
            result["off_in_ms"] = max(0, time.ticks_diff(self._off_at, time.ticks_ms()))
        return result

    def meta(self):
        return {"name": self.name, "driver": self.driver, "pin": self.pin}

    def deinit(self):
        self.set(False)
