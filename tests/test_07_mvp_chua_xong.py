"""TC-70..TC-77: chức năng MVP chưa có trong code (đánh dấu xfail).

Mỗi test mô tả hành vi cần có cho buổi demo. Hiện chúng "xfail" (dự kiến lỗi) nên
không làm đỏ cả bộ test. Làm xong chức năng nào thì xóa dòng `@pytest.mark.xfail`
của test đó; nếu đặt tên lệnh/đường dẫn khác thì sửa test cho khớp.
Nguồn: danh sách P1/P2 trong lần rà soát repo 17/11/2026.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import models
from support.device import firmware_modules

ROOT = Path(__file__).resolve().parents[1]
xfail = pytest.mark.xfail(strict=False)


def add_rule(system, metric="temperature", op=">", threshold=35.0, severity="warning"):
    with system.db() as db:
        db.add(models.AlertRule(id=f"rule-{metric}", barn_id="barn-1", metric=metric, op=op,
                                threshold=threshold, hold_samples=1, severity=severity))
        db.commit()


async def test_tc70_nhiet_do_vuot_nguong_sinh_canh_bao(system):
    add_rule(system)
    device = await system.online_device("barn-1")
    await device.send_telemetry({"room": {"temperature": 38.0, "humidity": 60}})
    alerts = (await system.call("operator", "GET", "/alerts", params={"status": "open"})).json()
    assert len(alerts) == 1 and alerts[0]["device_id"] == device.device_id


async def test_tc71_thiet_bi_mat_ket_noi_sinh_canh_bao(system):
    device = await system.online_device("barn-1")
    await device.power_loss()
    alerts = (await system.call("operator", "GET", "/alerts", params={"status": "open"})).json()
    assert any(a["device_id"] == device.device_id for a in alerts)


async def test_tc72_quat_tu_bat_khi_nong(system, monkeypatch):
    device = await system.online_device("barn-1")
    monkeypatch.setattr(device.ctx.fan_control.sensor, "_measure",
                        lambda: {"temperature": 36.0, "humidity": 70})
    device.ctx.control_tick()
    assert device.actuator_state("relay")["on"] is True


async def test_tc73_cam_bien_loi_thi_bat_quat(system):
    device = await system.online_device("barn-1")
    for _ in range(3):
        device.ctx.publish("telemetry", {"readings": {}, "errors": {"room": "timeout"}})
    await system.broker.settle()
    assert device.actuator_state("relay")["on"] is True


async def test_tc74_lenh_cho_an(system):
    assert "feed" in firmware_modules().commands.REGISTRY
    device = await system.online_device("barn-1")
    r = await system.call("operator", "POST", f"/devices/{device.device_id}/commands",
                          json={"name": "feed", "args": {"seconds": 1}, "timeout_s": 5})
    assert r.status_code == 200
    assert device.actuator_state("servo")["angle"] == 90  # đóng (90°) lại sau khi cho ăn


async def test_tc75_gui_lenh_theo_chuong(system):
    await system.online_device("barn-1")
    r = await system.call("operator", "POST", "/barns/barn-1/commands",
                          json={"action": "relay_set", "params": {"on": True}})
    assert r.status_code not in (404, 405)


def test_tc76_servo_khong_tu_quay_khi_khoi_dong():
    config = json.loads((ROOT / "firmware" / "config.example.json").read_text(encoding="utf-8"))
    for actuator in config["actuators"]:
        if actuator["driver"] == "servo":
            assert actuator.get("sequence", {}).get("autostart") is not True


@xfail(reason="Hạn chế: broker có TLS 8883 (just tls-cert) nhưng ESP32 không PSRAM treo khi bắt tay TLS; ESP32 dùng 1883 trong LAN riêng")
def test_tc77_esp32_dung_tls():
    config = json.loads((ROOT / "firmware" / "config.example.json").read_text(encoding="utf-8"))
    assert config["mqtt"]["port"] == 8883 or config["mqtt"].get("tls") or config["mqtt"].get("ssl")
