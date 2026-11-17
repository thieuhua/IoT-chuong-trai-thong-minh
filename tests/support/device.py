"""ESP32 ảo chạy chính code firmware MicroPython (firmware/src) trên máy tính.

Không viết lại logic thiết bị: dùng `App` (meta, đọc cảm biến, relay, servo),
`commands.dispatch` (xử lý lệnh, mã lỗi) và `core.protocol` (đóng gói tin) của
firmware. Chỉ thay phần mạng (umqtt + Wi-Fi) bằng broker trong bộ nhớ và làm lại
hai vòng lặp chặn `provisioning.run` / `session.run` theo đúng thứ tự của chúng.
"""
from __future__ import annotations

import asyncio
import gc
import importlib.util
import os
from pathlib import Path
import secrets
import sys
import time
import types

from .broker import InMemoryBroker, NotAuthorised

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_SRC = ROOT / "firmware" / "src"
FIRMWARE_STUBS = ROOT / "firmware" / "tests" / "stubs"

_START = time.monotonic()


def _install_board_shims() -> None:
    """Các hàm MicroPython mà CPython không có (giống firmware/tests/conftest.py)."""
    for path in (str(FIRMWARE_STUBS), str(FIRMWARE_SRC)):
        if path not in sys.path:
            sys.path.append(path)  # sau backend/: `app` vẫn là package backend
    if not hasattr(time, "ticks_ms"):
        time.ticks_ms = lambda: int((time.monotonic() - _START) * 1000) % (1 << 30)
        time.ticks_add = lambda ticks, delta: (ticks + delta) % (1 << 30)
        time.ticks_diff = lambda a, b: ((a - b + (1 << 29)) % (1 << 30)) - (1 << 29)
        time.sleep_ms = lambda ms: time.sleep(ms / 1000)
    if not hasattr(gc, "mem_free"):
        gc.mem_free = lambda: 100000


_firmware = None


def firmware_modules():
    """Nạp firmware một lần, dưới tên `fw_app` để không đụng package `app` của backend."""
    global _firmware
    if _firmware is None:
        _install_board_shims()
        from core import storage, identity, protocol, ota  # noqa: F401  (firmware/src/core)
        import commands
        # Windows không cho os.rename đè file có sẵn; board thì cho. Chỉ đổi trong module firmware.
        storage.os = types.SimpleNamespace(rename=os.replace, remove=os.remove)
        spec = importlib.util.spec_from_file_location("fw_app", FIRMWARE_SRC / "app.py")
        fw_app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fw_app)
        _firmware = types.SimpleNamespace(app=fw_app, commands=commands, protocol=protocol,
                                          identity=identity, ota=ota)
    return _firmware


DEFAULT_CONFIG = {
    "wifi": {"ssid": "test", "password": "test"},
    "mqtt": {"host": "broker.test", "bootstrap_user": "bootstrap", "bootstrap_password": "bootstrap-pw"},
    "ntp": False,
    "interval_s": 10,
    "sensors": [{"driver": "simulated", "name": "room"}],
    # Giống config.example.json nhưng tắt autostart: test không cần servo tự quét.
    "actuators": [
        {"driver": "servo", "name": "servo", "pin": 14, "min_us": 500, "max_us": 2400,
         "sequence": {"angles": [0, 90, 180], "step_ms": 1000, "autostart": False},
         "max_dps": 0, "detach_ms": 0, "start_delay_ms": 0},
        {"driver": "relay", "name": "relay", "pin": 26, "active_low": False, "initial": False, "max_on_ms": 0},
    ],
}


class _Link:
    """Thay MQTTLink của firmware: publish đi thẳng vào broker trong bộ nhớ."""

    def __init__(self, device: "FirmwareDevice", session):
        self.device, self.session = device, session

    def publish(self, topic, payload, retain=False, qos=0):
        if isinstance(topic, bytes):
            topic = topic.decode()
        self.device.sent.append((topic, payload))
        self.device.broker.publish(self.session, topic, payload, retain)


class FirmwareDevice:
    def __init__(self, broker: InMemoryBroker, state_dir: Path, *, hw_id: str | None = None,
                 config: dict | None = None, bootstrap_password: str = "bootstrap-pw"):
        fw = firmware_modules()
        self.fw = fw
        self.broker = broker
        self.bootstrap_password = bootstrap_password
        state_dir.mkdir(parents=True, exist_ok=True)
        self.identity = fw.identity.Identity(str(state_dir / "state.json"), str(state_dir / "device.json"))
        # Stub machine.unique_id() trả cùng một giá trị: gán hw_id riêng cho từng thiết bị ảo.
        self.identity.hw_id = hw_id or secrets.token_hex(6)
        cfg = dict(DEFAULT_CONFIG if config is None else config)
        cfg["mqtt"] = dict(cfg["mqtt"], bootstrap_password=bootstrap_password)
        self.ctx = fw.app.App(cfg, self.identity)
        self.session = None
        self.sent: list[tuple[str, bytes]] = []
        self.provision_replies: list[dict] = []
        self.silent = False  # True: nhận lệnh nhưng không trả lời (giả lập treo)
        self.reply_delay_s = 0.0

    # Định danh -----------------------------------------------------------------
    @property
    def hw_id(self) -> str:
        return self.identity.hw_id

    @property
    def password(self) -> str:
        return self.identity.device["password"]

    @property
    def device_id(self) -> str | None:
        return self.identity.device.get("device_id") if self.identity.device else None

    def topic(self, leaf: str) -> str:
        return self.fw.protocol.device_topic(self.device_id, leaf)

    # Đăng ký (giống core/provisioning.run) ----------------------------------------
    async def request_provisioning(self) -> None:
        p = self.fw.protocol
        response_topic = p.provision_response_topic(self.hw_id)
        if self.session is None or not self.session.connected:
            self.session = self.broker.connect(self.hw_id, "bootstrap", self.bootstrap_password)
            self.ctx.link = _Link(self, self.session)
            self.broker.subscribe(self.session, response_topic, self._on_provision)
        data = self.ctx.meta()
        del data["interval_s"]
        data["password"] = self.password
        self.ctx.link.publish(p.provision_request_topic(self.hw_id), self.ctx.encode(p.PROVISION_REQUEST, data))
        await self.broker.settle()

    def _on_provision(self, topic, payload):
        p = self.fw.protocol
        try:
            data = p.decode(payload, p.PROVISION_RESPONSE)["data"]
        except p.ProtocolError:
            return
        self.provision_replies.append(data)
        if data.get("status") == "approved" and p.is_valid_device_id(data.get("device_id")):
            self.identity.approve(data["device_id"])

    # Phiên đã đăng ký (giống core/session.run) -------------------------------------
    async def go_online(self) -> None:
        p = self.fw.protocol
        if self.session is not None:
            self.broker.disconnect(self.session)
        device_id = self.device_id
        will = (self.topic(p.STATUS), self.ctx.encode(p.STATUS, {"state": "offline", "reason": "lwt"}), True)
        try:
            self.session = self.broker.connect(device_id, device_id, self.password, will=will)
        except NotAuthorised:
            raise
        self.ctx.link = _Link(self, self.session)
        command_topic = self.topic(p.CMD)
        # Subscribe trước rồi mới báo online, đúng thứ tự trong session.run.
        if not self.broker.subscribe(self.session, command_topic, self._on_command):
            raise PermissionError(command_topic)
        self.ctx.publish(p.STATUS, {"state": "online"}, retain=True, qos=1)
        self.ctx.publish_meta()
        await self.broker.settle()

    async def provision_and_connect(self, approve) -> str:
        """Gửi yêu cầu, gọi `approve(hw_id)` (thường là API của admin), rồi lên mạng."""
        await self.request_provisioning()
        await approve(self.hw_id)
        await self.broker.settle()
        assert self.device_id, f"chưa được duyệt: {self.provision_replies}"
        await self.go_online()
        return self.device_id

    def _on_command(self, topic, payload):
        if self.silent:
            return None

        async def answer():
            if self.reply_delay_s:
                await asyncio.sleep(self.reply_delay_s)
            self.fw.commands.dispatch(self.ctx, payload)
            if self.ctx.meta_dirty:  # session.run gửi lại meta khi set_interval đổi chu kỳ
                self.ctx.meta_dirty = False
                self.ctx.publish_meta()
            if self.ctx.reboot_requested:
                self.ctx.reboot_requested = False
                self.ctx.publish(self.fw.protocol.STATUS, {"state": "offline", "reason": "reboot"},
                                 retain=True, qos=1)
                self.broker.disconnect(self.session)
                self.rebooted = True
        return answer()

    async def send_telemetry(self, readings: dict | None = None) -> None:
        """Một chu kỳ telemetry; mặc định đọc cảm biến thật của firmware (driver simulated)."""
        p = self.fw.protocol
        data = self.ctx.read_sensors() if readings is None else {"readings": readings}
        self.ctx.publish(p.TELEMETRY, data)
        await self.broker.settle()

    async def power_loss(self) -> None:
        """Rút điện: broker phát Last Will."""
        self.broker.disconnect(self.session, graceful=False)
        await self.broker.settle()

    def actuator_state(self, name: str) -> dict:
        return self.ctx.actuator(name).state()
