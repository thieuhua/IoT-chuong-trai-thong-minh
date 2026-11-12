"""Hobby servo (e.g. SG90) on a 50 Hz PWM pin, with an optional repeating angle sequence.

cfg: {"driver": "servo", "name": "gate", "pin": 26, "min_us": 500, "max_us": 2400,
      "sequence": {"angles": [0, 20, ..., 180], "step_ms": 1000, "autostart": true}}
"""
import time
from machine import PWM, Pin

PERIOD_US = 20000  # 50 Hz


def _angle(value):
    if type(value) is not int or not 0 <= value <= 180:
        raise ValueError("angle must be an integer in 0..180")
    return value


def _angles(values):
    if not isinstance(values, list) or not values:
        raise ValueError("angles must be a nonempty list")
    return [_angle(v) for v in values]


def _step_ms(value):
    if type(value) is not int or not 100 <= value <= 60000:
        raise ValueError("step_ms must be an integer in 100..60000")
    return value


class Servo:
    driver = "servo"

    def __init__(self, cfg):
        self.name = cfg["name"]
        self.pin = cfg["pin"]
        self.min_us = cfg.get("min_us", 500)
        self.max_us = cfg.get("max_us", 2400)
        seq = cfg.get("sequence") or {}
        self.angles = _angles(seq["angles"]) if "angles" in seq else []
        self.step_ms = _step_ms(seq.get("step_ms", 1000))
        self.running = False
        self.angle = None
        self._index = 0
        self._next_at = 0
        self.pwm = PWM(Pin(self.pin), freq=50, duty_u16=0)
        if self.angles and seq.get("autostart", True):
            self.start()
        else:
            self.set_angle(_angle(cfg.get("initial", 90)))

    def _write(self, angle):
        pulse_us = self.min_us + (self.max_us - self.min_us) * angle // 180
        self.pwm.duty_u16(pulse_us * 65535 // PERIOD_US)
        self.angle = angle

    def set_angle(self, angle):
        """Move to one angle and stop the sequence."""
        self.running = False
        self._write(_angle(angle))

    def start(self, angles=None, step_ms=None):
        """(Re)start the sequence from its first angle; the first step happens on the next tick."""
        if angles is not None:
            self.angles = _angles(angles)
        if step_ms is not None:
            self.step_ms = _step_ms(step_ms)
        if not self.angles:
            raise ValueError("no sequence configured")
        self._index = 0
        self._next_at = time.ticks_ms()
        self.running = True

    def stop(self):
        self.running = False

    def tick(self, now):
        """Called every few ms from a hardware timer; advances one step every step_ms."""
        if not self.running or time.ticks_diff(now, self._next_at) < 0:
            return
        self._write(self.angles[self._index])
        self._index = (self._index + 1) % len(self.angles)
        self._next_at = time.ticks_add(self._next_at, self.step_ms)
        if time.ticks_diff(now, self._next_at) >= 0:
            # Fell behind (e.g. long blocking call): resync instead of replaying missed steps.
            self._next_at = time.ticks_add(now, self.step_ms)

    def state(self):
        return {"angle": self.angle, "running": self.running,
                "angles": self.angles, "step_ms": self.step_ms}

    def meta(self):
        return {"name": self.name, "driver": self.driver, "pin": self.pin, "range": [0, 180]}

    def deinit(self):
        self.running = False
        self.pwm.deinit()
