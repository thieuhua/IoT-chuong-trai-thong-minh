"""Hobby servo (e.g. SG90) on a 50 Hz PWM pin, with an optional repeating angle sequence.

cfg: {"driver": "servo", "name": "gate", "pin": 26, "min_us": 500, "max_us": 2400,
      "max_dps": 200, "detach_ms": 400, "start_delay_ms": 8000,
      "sequence": {"angles": [0, 20, ..., 180], "step_ms": 1000, "autostart": true}}

Power-saving options (all off by default) for boards that power the servo from USB:
- max_dps: move at most this many degrees per second instead of jumping (lower inrush current).
- detach_ms: stop the PWM pulses this long after reaching the target (no holding current).
- start_delay_ms: wait after boot before the sequence starts (do not overlap Wi-Fi start-up).
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
        self.max_dps = cfg.get("max_dps")
        self.detach_ms = cfg.get("detach_ms", 0)
        seq = cfg.get("sequence") or {}
        self.angles = _angles(seq["angles"]) if "angles" in seq else []
        self.step_ms = _step_ms(seq.get("step_ms", 1000))
        self.running = False
        self.angle = None       # target angle
        self.position = None    # angle currently being driven (differs while slewing)
        self.attached = False
        self._index = 0
        self._next_at = 0
        self._last_tick = None
        self._reached_at = None
        self.pwm = PWM(Pin(self.pin), freq=50, duty_u16=0)
        if self.angles and seq.get("autostart", True):
            self.start()
            self._next_at = time.ticks_add(time.ticks_ms(), cfg.get("start_delay_ms", 0))
        else:
            self.set_angle(_angle(cfg.get("initial", 90)))

    def _drive(self, position):
        pulse_us = self.min_us + int((self.max_us - self.min_us) * position) // 180
        self.pwm.duty_u16(pulse_us * 65535 // PERIOD_US)
        self.position = position
        self.attached = True

    def _target(self, angle, now=None):
        self.angle = angle
        self._reached_at = None
        if self.max_dps is None or self.position is None:
            # No slewing configured, or unknown start position: go there directly.
            self._drive(angle)
            self._reached_at = time.ticks_ms() if now is None else now

    def set_angle(self, angle):
        """Move to one angle and stop the sequence."""
        self.running = False
        self._target(_angle(angle))

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
        """Called every few ms from a hardware timer."""
        dt = 0 if self._last_tick is None else time.ticks_diff(now, self._last_tick)
        self._last_tick = now
        if self.running and time.ticks_diff(now, self._next_at) >= 0:
            self._target(self.angles[self._index], now)
            self._index = (self._index + 1) % len(self.angles)
            self._next_at = time.ticks_add(self._next_at, self.step_ms)
            if time.ticks_diff(now, self._next_at) >= 0:
                # Fell behind (e.g. long blocking call): resync instead of replaying missed steps.
                self._next_at = time.ticks_add(now, self.step_ms)
        if self.angle is not None and self.position != self.angle and dt > 0:
            step = self.max_dps * dt / 1000
            if abs(self.angle - self.position) <= step:
                self._drive(self.angle)
                self._reached_at = now
            else:
                self._drive(self.position + (step if self.angle > self.position else -step))
        elif (self.detach_ms and self.attached and self._reached_at is not None
              and time.ticks_diff(now, self._reached_at) >= self.detach_ms):
            self.pwm.duty_u16(0)  # no pulses: the servo stops holding and draws almost nothing
            self.attached = False

    def state(self):
        return {"angle": self.angle, "running": self.running,
                "angles": self.angles, "step_ms": self.step_ms}

    def meta(self):
        return {"name": self.name, "driver": self.driver, "pin": self.pin, "range": [0, 180]}

    def deinit(self):
        self.running = False
        self.pwm.deinit()
