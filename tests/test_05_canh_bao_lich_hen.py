"""TC-40..TC-46: cảnh báo (xem/xác nhận/đóng), lịch hẹn chạy lệnh, nhật ký audit."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest

from app import models
from app.main import app as fastapi_app
from app.services import scheduler


def add_alert(system, device_id, severity="warning"):
    alert_id = str(uuid.uuid4())
    with system.db() as db:
        rule_id = str(uuid.uuid4())
        db.add(models.AlertRule(id=rule_id, barn_id="barn-1", metric="temperature", op=">",
                                threshold=35, hold_samples=1, severity=severity))
        db.add(models.Alert(id=alert_id, rule_id=rule_id, device_id=device_id, severity=severity,
                            status="open", raised_at=datetime.utcnow()))
        db.commit()
    return alert_id


@pytest.fixture
async def device(system):
    return await system.online_device("barn-1")


async def test_tc40_xem_canh_bao_theo_chuong_duoc_gan(system, device):
    add_alert(system, device.device_id)
    for role, count in (("admin", 1), ("operator", 1), ("viewer", 1), ("operator2", 0)):
        r = await system.call(role, "GET", "/alerts")
        assert r.status_code == 200 and len(r.json()) == count, role


async def test_tc41_xac_nhan_roi_dong_canh_bao(system, device):
    alert_id = add_alert(system, device.device_id, "critical")
    r = await system.call("operator", "POST", f"/alerts/{alert_id}/ack", json={"note": "đã bật quạt"})
    assert r.status_code == 200 and r.json()["status"] == "acknowledged"
    assert r.json()["handled_by"] == system.users["operator"]
    r = await system.call("operator", "POST", f"/alerts/{alert_id}/close", json={"note": "nhiệt độ đã giảm"})
    assert r.status_code == 200 and r.json()["status"] == "closed" and r.json()["closed_at"]
    assert (await system.call("operator", "POST", f"/alerts/{alert_id}/close", json={})).status_code == 409
    assert (await system.call("operator", "POST", f"/alerts/{alert_id}/ack", json={})).status_code == 409
    r = await system.call("viewer", "GET", "/alerts", params={"status": "closed"})
    assert [a["id"] for a in r.json()] == [alert_id]
    assert {"alert.acknowledge", "alert.close"} <= set(system.audit_actions())


async def test_tc42_loc_trang_thai_sai_bi_400(system):
    assert (await system.call("admin", "GET", "/alerts", params={"status": "abc"})).status_code == 400


async def schedule(system, device, run_in_s=3600, **extra):
    body = {"device_id": device.device_id, "command_name": "relay_set", "args": {"on": True},
            "run_at": (datetime.now(timezone.utc) + timedelta(seconds=run_in_s)).isoformat(), **extra}
    return await system.call("operator", "POST", "/barns/barn-1/scheduled-events", json=body)


def make_due(system, event_id):
    with system.db() as db:
        db.query(models.ScheduledEvent).filter_by(id=event_id).update(
            {"run_at": datetime.utcnow() - timedelta(seconds=1)})
        db.commit()


async def test_tc43_lich_hen_den_gio_thi_gui_lenh_xuong_esp32(system, device):
    r = await schedule(system, device)
    assert r.status_code == 201
    event_id = r.json()["id"]
    make_due(system, event_id)  # "tua nhanh" tới giờ chạy
    assert await scheduler.asyncio.to_thread(scheduler.get_due_events_sync) == [event_id]
    await scheduler.execute_event(fastapi_app, event_id)
    assert device.actuator_state("relay")["on"] is True
    with system.db() as db:
        event = db.get(models.ScheduledEvent, event_id)
        assert event.status == "succeeded" and event.executed_at is not None
    assert {"scheduled_event.create", "scheduled_event.start", "scheduled_event.complete"} <= set(system.audit_actions())


async def test_tc44_lich_lap_hang_ngay_doi_sang_ngay_hom_sau(system, device):
    r = await schedule(system, device, repeat_type="daily")
    event_id = r.json()["id"]
    make_due(system, event_id)
    with system.db() as db:
        due_at = db.get(models.ScheduledEvent, event_id).run_at
    await scheduler.execute_event(fastapi_app, event_id)
    with system.db() as db:
        event = db.get(models.ScheduledEvent, event_id)
        assert event.status == "pending" and event.run_at == due_at + timedelta(days=1)


async def test_tc45_lich_hen_that_bai_khi_thiet_bi_offline(system, device):
    event_id = (await schedule(system, device)).json()["id"]
    make_due(system, event_id)
    await device.power_loss()
    await scheduler.execute_event(fastapi_app, event_id)
    with system.db() as db:
        event = db.get(models.ScheduledEvent, event_id)
        assert event.status == "failed" and event.error


async def test_tc46_kiem_tra_du_lieu_lich_hen(system, device):
    assert (await schedule(system, device, run_in_s=-60)).status_code == 422  # giờ đã qua
    body = {"device_id": device.device_id, "command_name": "relay_set",
            "run_at": (datetime.now() + timedelta(hours=1)).isoformat()}  # thiếu múi giờ
    assert (await system.call("operator", "POST", "/barns/barn-1/scheduled-events", json=body)).status_code == 422
    other = await system.online_device("barn-2")
    body = {"device_id": other.device_id, "command_name": "relay_set",
            "run_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    # Thiết bị chuồng 2 không được hẹn giờ qua chuồng 1
    assert (await system.call("operator", "POST", "/barns/barn-1/scheduled-events", json=body)).status_code == 404
    event_id = (await schedule(system, device)).json()["id"]
    assert (await system.call("operator2", "DELETE", f"/scheduled-events/{event_id}")).status_code == 403
    assert (await system.call("operator", "DELETE", f"/scheduled-events/{event_id}")).status_code == 200
    assert (await system.call("operator", "DELETE", f"/scheduled-events/{event_id}")).status_code == 409


async def test_tc47_admin_xem_nhat_ky_audit(system, device):
    await system.call("operator", "PATCH", f"/devices/{device.device_id}", json={"name": "Quạt chuồng 1"})
    r = await system.call("admin", "GET", "/audit-logs")
    assert r.status_code == 200
    rows = r.json()
    rename = [row for row in rows if row["action"] == "device.rename"]
    assert rename and rename[0]["user_id"] == system.users["operator"]
    assert rename[0]["target"] == f"devices:{device.device_id}"
