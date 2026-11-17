"""TC-30..TC-39: điều khiển có phản hồi (cmd → resp) qua API, tới code firmware thật.

Hướng hiện tại của repo: lệnh `relay_set` (quạt/đèn qua relay GPIO26), `servo_set`
/ `servo_sequence` (máng ăn, servo GPIO14), phản hồi 1 bước `resp` có `re` = id lệnh.
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from iot_core import protocol as p


@pytest.fixture
async def device(system):
    return await system.online_device("barn-1")


async def command(system, device, name, args=None, who="operator", **extra):
    body = {"name": name, "args": args or {}, **extra}
    return await system.call(who, "POST", f"/devices/{device.device_id}/commands", json=body)


async def test_tc30_bat_tat_quat_qua_relay(system, device):
    r = await command(system, device, "relay_set", {"on": True})
    assert r.status_code == 200 and r.json() == {"on": True}
    assert device.actuator_state("relay")["on"] is True
    pin = device.ctx.actuator("relay").output
    assert pin.value() == 1  # chân GPIO26 lên mức cao
    r = await command(system, device, "relay_set", {"on": False})
    assert r.json() == {"on": False} and pin.value() == 0


async def test_tc31_bat_quat_co_hen_gio_tu_tat(system, device):
    r = await command(system, device, "relay_set", {"on": True, "duration_ms": 60000})
    state = r.json()
    assert state["on"] is True and 0 < state["off_in_ms"] <= 60000


async def test_tc32_quay_servo_may_cho_an(system, device):
    r = await command(system, device, "servo_set", {"angle": 90})
    assert r.status_code == 200
    assert r.json()["angle"] == 90 and r.json()["running"] is False
    r = await command(system, device, "actuator_state")
    assert set(r.json()) == {"servo", "relay"}


@pytest.mark.parametrize("name,args,code", [
    ("relay_set", {"on": "bat"}, "bad_args"),             # sai kiểu
    ("relay_set", {"on": False, "duration_ms": 1000}, "bad_args"),
    ("servo_set", {"angle": 270}, "bad_args"),             # ngoài 0..180
    ("relay_set", {"name": "khong-co", "on": True}, "actuator_not_found"),
    ("tu_huy", {}, "unknown_command"),
    ("ping", {"thua": 1}, "bad_args"),
])
async def test_tc33_lenh_sai_bi_thiet_bi_tu_choi_va_bao_ma_loi(system, device, name, args, code):
    r = await command(system, device, name, args)
    assert r.status_code == 502
    assert r.json()["code"] == code
    assert device.actuator_state("relay")["on"] is False


async def test_tc34_thiet_bi_khong_tra_loi_thi_het_gio_504(system, device):
    device.silent = True
    started = time.perf_counter()
    r = await command(system, device, "relay_set", {"on": True}, timeout_s=0.5)
    elapsed = time.perf_counter() - started
    assert r.status_code == 504
    assert 0.5 <= elapsed < 1.5
    assert not system.gateway._pending  # không rò lệnh treo


async def test_tc35_thiet_bi_offline_bao_409_khong_gui_lenh(system, device):
    await device.power_loss()
    before = len(system.broker.log)
    r = await command(system, device, "relay_set", {"on": True})
    assert r.status_code == 409
    assert not [t for _, t, _ in system.broker.log[before:] if t.endswith("/cmd")]


async def test_tc36_thiet_bi_khong_ton_tai_404(system):
    r = await system.call("admin", "POST", "/devices/esp32-000000000000/commands", json={"name": "ping"})
    assert r.status_code == 404


async def test_tc37_ping_do_uptime(system, device):
    r = await system.call("operator", "POST", f"/devices/{device.device_id}/ping")
    assert r.status_code == 200 and isinstance(r.json()["uptime_s"], int)


async def test_tc38_nhieu_lenh_dong_thoi_khong_nham_phan_hoi(system):
    """3 thiết bị × 4 lệnh cùng lúc: mỗi phản hồi về đúng lệnh của nó (ghép theo `re`).
    Giữ ≤ 15 yêu cầu đồng thời: xem TC-87 về giới hạn pool kết nối DB."""
    devices = [await system.online_device("barn-1") for _ in range(3)]
    for d in devices:
        d.reply_delay_s = 0.01

    async def one(d, i):
        angle = (i * 17) % 181
        r = await system.call("admin", "POST", f"/devices/{d.device_id}/commands",
                              json={"name": "servo_set", "args": {"angle": angle}})
        return r.status_code, r.json()["angle"], angle

    results = await asyncio.gather(*(one(d, i) for d in devices for i in range(4)))
    assert all(status == 200 and got == want for status, got, want in results)


async def test_tc39_lenh_mang_ttl_va_id_duy_nhat(system, device):
    for _ in range(3):
        await command(system, device, "ping")
    sent = [json.loads(payload) for _, topic, payload in system.broker.log if topic == device.topic(p.CMD)]
    assert len({m["id"] for m in sent}) == 3
    assert all(m["data"]["ttl_s"] == 30 and isinstance(m["ts"], int) for m in sent)
