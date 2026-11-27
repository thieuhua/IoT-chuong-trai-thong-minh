"""TC-90..TC-95: kiểm lại bảo mật và độ trễ trên Mosquitto thật (Dynamic Security).

Cần broker của nhóm đang chạy:  docker compose -f deployment/compose.yaml up -d --wait
Đọc mật khẩu từ deployment/.env (hoặc biến IOT_TEST_ENV_FILE). Không có broker thì
các test này tự bỏ qua. Thiết bị test có hw_id bắt đầu bằng `7e57` và được dọn sau khi chạy.
ESP32 giả ở đây là backend/tools/sim_device.py (paho-mqtt) của nhóm.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import secrets
import socket
import statistics
import threading
import time
import uuid

import paho.mqtt.client as mqtt
import pytest

from iot_core import DeviceGateway, GatewayConfig
from iot_core import protocol as p

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.broker_that


async def eventually(predicate, timeout=15):
    async with asyncio.timeout(timeout):
        while True:
            result = await predicate()
            if result:
                return result
            await asyncio.sleep(0.05)


@pytest.fixture
async def real(tmp_path):
    env_file = Path(os.environ.get("IOT_TEST_ENV_FILE", ROOT / "deployment" / ".env"))
    if not env_file.is_file():
        pytest.skip(f"không có {env_file}")
    config = GatewayConfig.from_env(env_file)
    if not config.password or not config.bootstrap_password:
        pytest.skip("thiếu MQTT_BACKEND_PASSWORD / MQTT_BOOTSTRAP_PASSWORD")
    try:
        with socket.create_connection((config.broker_host, config.broker_port), timeout=1):
            pass
    except OSError:
        pytest.skip(f"không kết nối được {config.broker_host}:{config.broker_port}")
    config.db_path = tmp_path / "broker-that.sqlite3"
    config.auto_approve = False
    config.command_timeout_s = 5
    config.client_id_prefix = "backend-test-" + uuid.uuid4().hex[:6]
    async with DeviceGateway.from_config(config) as gateway:
        yield gateway


class Client:
    """Client paho đồng bộ, đủ để thử đăng nhập/publish/subscribe."""

    def __init__(self, host, port, client_id, username, password):
        self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv311)
        self.c.username_pw_set(username, password)
        self.connected, self.subacks, self.messages = threading.Event(), {}, []
        self.refused = None
        self.c.on_connect = self._on_connect
        self.c.on_subscribe = lambda c, u, mid, codes, props: self.subacks.setdefault(mid, codes)
        self.c.on_message = lambda c, u, m: self.messages.append((m.topic, bytes(m.payload)))
        self.c.connect(host, port)
        self.c.loop_start()
        self.connected.wait(5)

    def _on_connect(self, client, userdata, flags, reason, properties):
        self.refused = reason.is_failure
        self.connected.set()

    def subscribe_ok(self, topic) -> bool:
        _, mid = self.c.subscribe(topic, 1)
        deadline = time.time() + 5
        while mid not in self.subacks and time.time() < deadline:
            time.sleep(0.02)
        return not self.subacks[mid][0].is_failure

    def close(self):
        self.c.disconnect()
        self.c.loop_stop()


@pytest.fixture
async def approved(real, tmp_path):
    """Một thiết bị giả (sim_device) đã duyệt và online trên broker thật."""
    from tools.sim_device import SimDevice
    gw = real
    hw = "7e57" + uuid.uuid4().hex[:8]
    sim = SimDevice(hw, gw.config.broker_host, gw.config.broker_port, gw.config.bootstrap_password,
                    tmp_path / "sim", retry_s=0.2, interval_s=1)
    sim.start()
    try:
        async def pending():
            return any(r.hw_id == hw for r in await gw.list_registrations())
        await eventually(pending)
        device = await gw.approve(hw, device_id=p.default_device_id(hw))

        async def online():
            return (await gw.get_device(device.device_id)).online
        await eventually(online)
        yield gw, sim, device.device_id
    finally:
        await asyncio.to_thread(sim.stop)
        await gw.broker_auth.remove_device_account(p.default_device_id(hw))
        for leaf in (p.STATUS, p.META):
            await gw.transport.publish(p.device_topic(p.default_device_id(hw), leaf), b"", qos=1, retain=True)


async def test_tc90_dang_nhap_sai_bi_broker_tu_choi(real):
    cfg = real.config
    for client_id, user, password in (("7e57-x", "bootstrap", "sai"), ("7e57-y", "khong-co", "abc"),
                                      ("7e57-z", None, None)):
        c = await asyncio.to_thread(Client, cfg.broker_host, cfg.broker_port, client_id, user, password)
        try:
            assert c.refused is not False, (user, "đăng nhập được")
        finally:
            c.close()


async def test_tc91_bootstrap_khong_doc_yeu_cau_dang_ky(real):
    cfg = real.config
    c = await asyncio.to_thread(Client, cfg.broker_host, cfg.broker_port, "7e57" + secrets.token_hex(4),
                                "bootstrap", cfg.bootstrap_password)
    try:
        assert c.refused is False
        assert await asyncio.to_thread(c.subscribe_ok, "iot/v1/provision/+/request") is False
        assert await asyncio.to_thread(c.subscribe_ok, "iot/v1/#") is False
    finally:
        c.close()


async def test_tc92_thiet_bi_chi_dung_topic_cua_minh(approved):
    gw, sim, device_id = approved
    await asyncio.to_thread(sim.stop)  # nhường client id đã ghim cho client thử
    cfg = gw.config
    received = []
    other = p.device_topic("7e57-thiet-bi-khac", p.TELEMETRY)
    own = p.device_topic(device_id, p.TELEMETRY)
    for topic in (other, own):
        await gw.transport.subscribe(topic, lambda t, pl: received.append((t, pl)))
    c = await asyncio.to_thread(Client, cfg.broker_host, cfg.broker_port, device_id, device_id, sim.password)
    try:
        assert c.refused is False
        marker = secrets.token_hex(8).encode()
        c.c.publish(other, marker)
        c.c.publish(own, marker)

        async def got_own():
            return (own, marker) in received
        await eventually(got_own)
        await asyncio.sleep(0.3)
        assert (other, marker) not in received                     # không giả mạo được thiết bị khác
        assert await asyncio.to_thread(c.subscribe_ok, p.device_topic("7e57-thiet-bi-khac", p.CMD)) is False
        assert await asyncio.to_thread(c.subscribe_ok, "iot/v1/#") is False
        assert await asyncio.to_thread(c.subscribe_ok, p.device_topic(device_id, p.CMD)) is True
    finally:
        c.close()
    # Đúng mật khẩu nhưng client id khác → bị từ chối (client id bị ghim)
    c = await asyncio.to_thread(Client, cfg.broker_host, cfg.broker_port, "7e57-khac", device_id, sim.password)
    try:
        assert c.refused is not False
    finally:
        c.close()


async def test_tc93_thu_hoi_thi_khong_dang_nhap_duoc(approved):
    gw, sim, device_id = approved
    password = sim.password
    await gw.revoke(device_id)
    await asyncio.to_thread(sim.stop)
    cfg = gw.config
    c = await asyncio.to_thread(Client, cfg.broker_host, cfg.broker_port, device_id, device_id, password)
    try:
        assert c.refused is not False
    finally:
        c.close()


async def test_tc94_do_tre_lenh_tren_broker_that(approved, do_luong):
    gw, _, device_id = approved
    times = []
    for _ in range(50):
        started = time.perf_counter()
        await gw.ping(device_id)
        times.append(time.perf_counter() - started)
    median, worst = statistics.median(times) * 1000, max(times) * 1000
    do_luong("Lệnh ping khứ hồi qua Mosquitto thật (50 lần): trung vị", median, "ms",
             ghi_chu="broker thật, thiết bị giả sim_device")
    do_luong("Lệnh ping khứ hồi qua Mosquitto thật: lâu nhất", worst, "ms", nguong="≤ 2000 ms",
             dat=worst <= 2000)
    assert worst <= 2000


async def test_tc95_telemetry_qua_broker_that(approved, do_luong):
    gw, _, device_id = approved
    received = []
    gw.on_telemetry(lambda record: received.append(time.perf_counter()))
    started = time.perf_counter()

    async def three():
        return len(received) >= 3
    await eventually(three, timeout=10)  # sim gửi mỗi 1 s
    do_luong("Nhận 3 bản tin telemetry (chu kỳ 1 s) qua broker thật", time.perf_counter() - started, "s",
             nguong="≤ 5 s", dat=time.perf_counter() - started <= 5)
    assert await gw.latest_telemetry(device_id)
