"""Wi-Fi -> provisioning -> registered session; recover network failures."""
import gc
import machine
import time
import commands
from core import protocol as p
from core import provisioning, session, wifi
from core.clock import Clock
from core.identity import Identity
from core.mqtt_link import MQTTLink, NotAuthorised
from core.runtime import pause
from core.storage import load_json
from sensors import build_sensors
from sensors.base import SensorError
from umqtt.simple import MQTTException

FW_VERSION = "0.1.0"


class App:
    def __init__(self, config, identity=None):
        self.config = config
        self.identity = identity if identity is not None else Identity()
        self.clock = Clock()
        self.started_at = time.ticks_ms()
        self.interval_s = self.identity.state.get("interval_s", config.get("interval_s", 10))
        self.sensors = build_sensors(config.get("sensors", []))
        self.link = None
        self.reboot_requested = False
        self.meta_dirty = False
        self.auth_failures = 0
        self.backoff_s = 2
        timeout = config.get("watchdog_s", 0)
        self.watchdog = machine.WDT(timeout=timeout * 1000) if timeout > 0 else None
        print("ESP32 hw_id=%s fw=%s mem_free=%s" %
              (self.identity.hw_id, FW_VERSION, gc.mem_free()))

    def feed(self):
        if self.watchdog:
            self.watchdog.feed()

    def uptime_s(self):
        return time.ticks_diff(time.ticks_ms(), self.started_at) // 1000

    def meta(self):
        return {"hw_id": self.identity.hw_id, "model": "esp32", "fw": FW_VERSION,
                "sensors": [sensor.meta() for sensor in self.sensors],
                "commands": list(commands.REGISTRY), "interval_s": self.interval_s}

    def encode(self, msg_type, data):
        return p.encode(msg_type, data, self.identity.next_id(), self.clock.now())

    def new_link(self, client_id, user, password, handler):
        cfg = self.config["mqtt"]
        return MQTTLink(client_id, cfg["host"], port=cfg.get("port", 1883),
                        user=user, password=password, keepalive=cfg.get("keepalive", 30),
                        handler=handler)

    def publish(self, leaf, data, retain=False, qos=0):
        self.link.publish(p.device_topic(self.identity.device["device_id"], leaf),
                          self.encode(leaf, data), retain=retain, qos=qos)

    def publish_meta(self):
        self.publish(p.META, self.meta(), retain=True, qos=1)

    def read_sensors(self, name=None):
        readings, errors = {}, {}
        for sensor in self.sensors:
            if name is None or name == sensor.name:
                self.feed()
                try:
                    readings[sensor.name] = sensor.read()
                except SensorError as exc:
                    errors[sensor.name] = str(exc)
        result = {"readings": readings}
        if errors:
            result["errors"] = errors
        return result

    def run(self):
        while True:
            try:
                cfg = self.config["wifi"]
                wifi.connect(cfg["ssid"], cfg["password"], 20, self.feed)
                self.feed()
                if self.config.get("ntp", True) and not self.clock.synced:
                    self.clock.sync()
                    self.feed()
                if not self.identity.load_device().get("device_id"):
                    provisioning.run(self)
                session.run(self)
            # MQTTException (e.g. 3 server unavailable) and IndexError/AssertionError from umqtt
            # on short reads are network trouble too: back off instead of crashing to a reset.
            except (OSError, NotAuthorised, MQTTException, IndexError, AssertionError) as exc:
                print("Connection failed:", exc, "retry in", self.backoff_s)
                pause(self.backoff_s, self.feed)
                self.backoff_s = min(30, self.backoff_s * 2)


def run():
    config = load_json("/config.json", None)
    if config is None:
        raise ValueError("Copy config.example.json to src/config.json and deploy with -Config")
    App(config).run()
