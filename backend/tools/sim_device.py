"""MQTT device simulator matching the firmware protocol."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
from pathlib import Path
import secrets
import sys
import threading
import time

import paho.mqtt.client as mqtt

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iot_core import AuthMode, CommandFailed, GatewayConfig
from iot_core import protocol as p

logger = logging.getLogger("sim_device")
SENSORS = [{"name": "room", "driver": "dht11", "fields": {"temperature": "°C", "humidity": "%"}},
           {"name": "light", "driver": "bh1750", "fields": {"lux": "lx"}}]
COMMANDS = ["ping", "get_info", "read", "set_interval", "reboot",
            "ota_begin", "ota_chunk", "ota_commit", "ota_abort", "ota_status"]


class SimDevice:
    def __init__(self, hw_id: str, host: str, port: int, bootstrap_password: str | None,
                 state_dir: str | Path, retry_s: float = 10, interval_s: int = 10, auth: bool = True,
                 confirm_delay_s: float = 3, reboot_delay_s: float = 1):
        self.hw_id = hw_id
        self.host = host
        self.port = port
        self.bootstrap_password = bootstrap_password
        self.state_dir = Path(state_dir)
        self.retry_s = retry_s
        self.interval_s = interval_s
        self.auth = auth
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.state_dir / f"{hw_id}.json"
        state = json.loads(self._path.read_text()) if self._path.exists() else {}
        self.device_id = state.get("device_id")
        self.password = state.get("password") or secrets.token_hex(16)
        self.interval_s = state.get("interval_s", interval_s)
        self._save()
        self._stop = threading.Event()
        self._thread = None
        self.online = False
        self.login_refusals = 0
        self._boot = 0
        self.fw = "0.1.0"
        self.files: dict[str, bytes] = {}
        self.fail_next_update = False
        self.confirm_delay_s = confirm_delay_s
        self.reboot_delay_s = reboot_delay_s
        self._ota_state = "ok"
        self._ota_rx = None
        self._ota_pending = None
        self._trial_at = None
        self._rolled_back_from = None
        self._ota_boots = 0
        self._reboot_at = None

    def _save(self) -> None:
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"device_id": self.device_id, "password": self.password,
                                         "interval_s": self.interval_s}), encoding="utf-8")
        temporary.replace(self._path)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"sim-{self.hw_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _envelope(self, kind: str, data: dict) -> bytes:
        self._seq += 1
        return p.Envelope(kind, data, id=f"{self._boot}-{self._seq}").encode()

    def _publish(self, kind, data, qos=0, retain=False):
        return self._client.publish(p.device_topic(self.device_id, kind),
                                    self._envelope(kind, data), qos=qos, retain=retain)

    def _meta(self) -> dict:
        return dict(hw_id=self.hw_id, model="esp32-sim", fw=self.fw, sensors=SENSORS,
                    commands=COMMANDS, interval_s=self.interval_s, ota=self._ota_state)

    def _ota_command(self, name: str, args: dict) -> dict:
        def fail(message, code="ota_error"):
            raise CommandFailed(code, message)

        def receiving():
            rx = self._ota_rx
            if rx is None:
                fail("no update in progress")
            return rx

        if name == "ota_begin":
            version, entries = args.get("version"), args.get("files")
            if self._ota_rx and self._ota_rx["version"] == version and self._ota_rx["manifest"] == entries:
                rx = self._ota_rx
            else:
                self._ota_rx = None
                if self._ota_state != "ok":
                    fail("previous update is still " + self._ota_state)
                if not isinstance(version, str) or not 1 <= len(version) <= 40:
                    fail("invalid version", "bad_args")
                if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
                    fail("invalid manifest", "bad_args")
                specs = {}
                for entry in entries:
                    if not isinstance(entry, dict):
                        fail("invalid file entry", "bad_args")
                    path, size, digest = entry.get("path"), entry.get("size"), entry.get("sha256")
                    if (not isinstance(path, str) or not path or len(path) > 64 or path.startswith("/")
                            or ".." in path or "//" in path or path in ("main.py", "boot.py")
                            or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_-./" for c in path)
                            or not path.endswith((".py", ".mpy", ".json")) or path in specs
                            or type(size) is not int or size < 0 or not isinstance(digest, str) or len(digest) != 64):
                        fail("invalid path/size/sha256", "bad_args")
                    specs[path] = dict(size=size, sha256=digest)
                if "app.py" not in specs:
                    fail("update must contain app.py", "bad_args")
                staged = {path: bytearray() for path, spec in specs.items()
                          if path not in self.files or hashlib.sha256(self.files[path]).hexdigest() != spec["sha256"]}
                rx = dict(version=version, manifest=entries, specs=specs, staged=staged)
                self._ota_rx = rx
            return {"need": [path for path in rx["staged"] if rx["specs"][path]["size"]],
                    "written": {path: len(data) for path, data in rx["staged"].items()}}
        if name == "ota_chunk":
            rx = receiving()
            path, offset, data = args.get("path"), args.get("offset"), args.get("data")
            if not isinstance(path, str) or path not in rx["staged"] or type(offset) is not int or not isinstance(data, str):
                fail("invalid chunk", "bad_args")
            staged = rx["staged"][path]
            if offset >= len(staged):
                if offset != len(staged):
                    fail("unexpected offset", "bad_args")
                try:
                    raw = base64.b64decode(data, validate=True)
                except ValueError:
                    fail("invalid base64", "bad_args")
                if len(staged) + len(raw) > rx["specs"][path]["size"]:
                    fail("data beyond declared size", "bad_args")
                staged.extend(raw)
            return {"path": path, "written": len(staged)}
        if name == "ota_commit":
            rx = receiving()
            new_files = {}
            for path, spec in rx["specs"].items():
                data = bytes(rx["staged"][path]) if path in rx["staged"] else self.files[path]
                if len(data) != spec["size"] or hashlib.sha256(data).hexdigest() != spec["sha256"]:
                    fail("incomplete file or sha256 mismatch: " + path)
                new_files[path] = data
            # Config lives outside /app and survives a bundle which omits it.
            if "config.json" in self.files and "config.json" not in new_files:
                new_files["config.json"] = self.files["config.json"]
            self._ota_pending = (rx["version"], new_files, self.fw, self.files, self.fail_next_update)
            self.fail_next_update = False
            self._ota_rx = None
            self._ota_state = "committing"
            self._reboot_at = time.monotonic() + 0.2
            return {"version": rx["version"], "reboot": True}
        if name == "ota_abort":
            self._ota_rx = None
            return {}
        if name == "ota_status":
            rx = self._ota_rx
            return {"version": self.fw, "state": self._ota_state, "boots": self._ota_boots,
                    "rolled_back_from": self._rolled_back_from,
                    "receiving": None if rx is None else {"version": rx["version"],
                        "need": [path for path in rx["staged"] if rx["specs"][path]["size"]],
                        "written": {path: len(data) for path, data in rx["staged"].items()}}}
        fail("unknown OTA command", "unknown_command")

    def _install_update(self):
        if self._ota_pending is not None:
            version, files, previous, old_files, fail = self._ota_pending
            self._ota_pending = None
            self.fw, self.files = version, files
            self._ota_state, self._ota_boots = "trial", 1
            self._rolled_back_from = None
            self._trial_at = time.monotonic() + self.confirm_delay_s
            self._rollback = (previous, old_files) if fail else None
        self._ota_rx = None

    def _finish_trial(self):
        if self._rollback is not None:
            self._rolled_back_from = self.fw
            self.fw, self.files = self._rollback
        self._ota_state, self._ota_boots = "ok", 0
        self._trial_at = None
        self._publish(p.META, self._meta(), qos=1, retain=True)

    def _read(self, sensor: str | None = None) -> dict:
        readings = {"room": {"temperature": 24, "humidity": 61}, "light": {"lux": 120}}
        return {"readings": readings if sensor is None else {sensor: readings[sensor]}}

    def _on_connect(self, client, userdata, flags, reason, properties):
        if reason.is_failure:
            self._refused = reason == 135  # MQTT 3.1.1 not authorised mapped to MQTT 5 reason.
            self._failed = True
            return
        self._connected = True
        if self._registered:
            client.subscribe(p.device_topic(self.device_id, p.CMD), qos=1)
            self._publish(p.STATUS, {"state": "online"}, qos=1, retain=True)
            self._publish(p.META, self._meta(), qos=1, retain=True)
            self.online = True
        else:
            client.subscribe(p.provision_response_topic(self.hw_id), qos=1)

    def _on_disconnect(self, client, userdata, flags, reason, properties):
        self._connected = False
        self.online = False

    def _on_message(self, client, userdata, message):
        try:
            envelope = p.Envelope.decode(message.payload, p.CMD if self._registered else p.PROVISION_RESPONSE)
            if not self._registered:
                if envelope.data.get("status") == "approved":
                    device_id = envelope.data.get("device_id", "")
                    if p.is_valid_device_id(device_id):
                        self.device_id = device_id
                        self._save()
                        self._approved = True
                elif envelope.data.get("status") == "rejected":
                    self._rejected = True
                return
            if envelope.ts is not None and envelope.ts + envelope.data.get("ttl_s", 30) < time.time():
                return
            data = envelope.data
            name, args = data.get("name"), data.get("args", {})
            if not isinstance(args, dict):
                self._answer(envelope.id, code=p.ERR_BAD_ARGS, message="args must be an object")
                return
            if name in COMMANDS and name.startswith("ota_"):
                result = self._ota_command(name, args)
            elif name == "ping":
                result = {"uptime_s": int(time.monotonic() - self._boot_at)}
            elif name == "get_info":
                result = dict(self._meta(), uptime_s=int(time.monotonic() - self._boot_at),
                              mem_free=100000, rssi=-40, ip="127.0.0.1")
            elif name == "read":
                sensor = args.get("sensor")
                if sensor is not None and sensor not in ("room", "light"):
                    self._answer(envelope.id, code=p.ERR_SENSOR_NOT_FOUND, message=f"no sensor '{sensor}'")
                    return
                result = self._read(sensor)
            elif name == "set_interval":
                seconds = args.get("seconds")
                if isinstance(seconds, bool) or not isinstance(seconds, int) or not 1 <= seconds <= 3600:
                    self._answer(envelope.id, code=p.ERR_BAD_ARGS, message="seconds must be 1..3600")
                    return
                self.interval_s = seconds
                self._save()
                result = {"interval_s": seconds}
            elif name == "reboot":
                result = {}
                self._reboot_at = time.monotonic() + 0.2
            else:
                self._answer(envelope.id, code=p.ERR_UNKNOWN_COMMAND, message=str(name))
                return
            self._answer(envelope.id, result=result)
        except p.ProtocolError:
            logger.warning("Invalid message on %s", message.topic)
        except CommandFailed as exc:
            self._answer(envelope.id, code=exc.code, message=exc.message)
        except Exception:
            logger.exception("Simulator command failed")
            if self._registered:
                self._answer(envelope.id, code=p.ERR_INTERNAL, message="internal error")

    def _answer(self, reference, result=None, code=None, message=""):
        data = {"re": reference, "ok": code is None}
        if code:
            data["error"] = {"code": code, "message": message}
        else:
            data["result"] = result or {}
        self._publish(p.RESP, data, qos=0)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._install_update()
            self._boot += 1
            self._seq = 0
            self._boot_at = time.monotonic()
            self._registered = bool(self.device_id)
            self._connected = self._failed = self._refused = self._approved = self._rejected = False
            self._reboot_at = None
            self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                       client_id=self.device_id or self.hw_id,
                                       clean_session=True, protocol=mqtt.MQTTv311)
            self._client.connect_timeout = 3
            if self.auth:
                self._client.username_pw_set(self.device_id or "bootstrap",
                                             self.password if self._registered else self.bootstrap_password)
            self._client.on_connect = self._on_connect
            self._client.on_message = self._on_message
            self._client.on_disconnect = self._on_disconnect
            if self._registered:
                self._client.will_set(p.device_topic(self.device_id, p.STATUS),
                                      self._envelope(p.STATUS, {"state": "offline", "reason": "lwt"}),
                                      qos=1, retain=True)
            reboot = False
            try:
                self._client.connect(self.host, self.port, keepalive=15)
                next_request = next_telemetry = 0
                while not self._stop.is_set() and not self._failed and not self._approved:
                    rc = self._client.loop(timeout=0.1)
                    if rc != mqtt.MQTT_ERR_SUCCESS:
                        break
                    now = time.monotonic()
                    if self.online and self._trial_at is not None and now >= self._trial_at:
                        self._finish_trial()
                    if self._connected and self._registered and now >= next_telemetry:
                        self._publish(p.TELEMETRY, self._read(), qos=0)
                        next_telemetry = now + self.interval_s
                    if self._connected and not self._registered and not self._rejected and now >= next_request:
                        data = dict(self._meta(), password=self.password)
                        self._client.publish(p.provision_request_topic(self.hw_id),
                                             self._envelope(p.PROVISION_REQUEST, data), qos=0)
                        next_request = now + self.retry_s
                    if self._reboot_at is not None and now >= self._reboot_at:
                        self._publish(p.STATUS, {"state": "offline", "reason": "reboot"}, qos=1, retain=True)
                        self._client.loop(timeout=0.1)
                        reboot = True
                        break
                if self._stop.is_set() and self.online:
                    self._publish(p.STATUS, {"state": "offline", "reason": "shutdown"}, qos=1, retain=True)
                    self._client.loop(timeout=0.1)
                self._client.disconnect()
                self._client.loop(timeout=0.1)
            except OSError:
                logger.debug("Simulator connection unavailable")
            finally:
                self.online = False
                if self._registered and self._refused:
                    self.login_refusals += 1
                    self._path.unlink(missing_ok=True)
                    self.device_id = None
                self._stop.wait(self.reboot_delay_s if reboot else 0.2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--env", default="../deployment/.env")
    parser.add_argument("--state-dir", default="data/sim")
    parser.add_argument("--confirm-delay", type=float, default=3)
    parser.add_argument("--fail-next-update", action="store_true")
    args = parser.parse_args()
    config = GatewayConfig.from_env(args.env)
    devices = [SimDevice(f"51a{i:09x}", config.broker_host, config.broker_port,
                         config.bootstrap_password, args.state_dir, auth=config.auth_mode == AuthMode.DYNSEC,
                         confirm_delay_s=args.confirm_delay)
               for i in range(1, args.count + 1)]
    try:
        for device in devices:
            device.fail_next_update = args.fail_next_update
            device.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for device in devices:
            device.stop()


if __name__ == "__main__":
    main()
