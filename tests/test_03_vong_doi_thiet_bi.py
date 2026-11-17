"""TC-20..TC-27: vòng đời thiết bị từ đầu đến cuối.

ESP32 ảo chạy code firmware thật (firmware/src), nói chuyện với backend qua broker
MQTT có Dynamic Security, đúng giao thức docs/protocol.md (topic iot/v1/...).
"""
from __future__ import annotations

import json

from app import models
from iot_core import protocol as p


async def test_tc20_vong_doi_day_du(system):
    """Đăng ký → chờ duyệt → admin duyệt → cấp tài khoản MQTT → online → gửi dữ liệu
    → nhận lệnh → đổi cấu hình → khởi động lại → mất điện (LWT) → thu hồi → bị chặn."""
    device = system.new_device()

    # 1. ESP32 mới gửi yêu cầu đăng ký bằng tài khoản bootstrap dùng chung
    await device.request_provisioning()
    assert device.provision_replies[-1]["status"] == "pending"
    r = await system.call("admin", "GET", "/registrations")
    pending = [row for row in r.json() if row["hw_id"] == device.hw_id]
    assert len(pending) == 1 and pending[0]["status"] == "pending"

    # 2. Admin duyệt → backend tạo tài khoản MQTT riêng + role chỉ cho topic của nó
    await system.approve_via_api(device.hw_id)
    await system.broker.settle()
    assert device.device_id == p.default_device_id(device.hw_id)
    account = system.broker.accounts[device.device_id]
    assert account.password == device.password and account.clientid == device.device_id

    # 3. Đăng nhập bằng tài khoản riêng, báo online, gửi meta (cảm biến, actuator, lệnh)
    await device.go_online()
    info = (await system.call("viewer", "GET", f"/devices/{device.device_id}")).json()
    assert info["online"] is True
    assert info["model"] == "esp32" and "relay_set" in info["commands"]
    assert [s["name"] for s in info["sensors"]] == ["room"]

    # 4. Gán vào chuồng, gửi telemetry, người dùng xem được
    await system.call("admin", "PUT", f"/devices/{device.device_id}/barn", json={"barn_id": "barn-1"})
    await device.send_telemetry({"room": {"temperature": 31.5, "humidity": 70}})
    latest = (await system.call("viewer", "GET", f"/devices/{device.device_id}/telemetry/latest")).json()
    assert latest["readings"]["values"]["room"] == {"temperature": 31.5, "humidity": 70}

    # 5. Operator bật quạt (relay) → ESP32 bật thật → phản hồi về
    r = await system.call("operator", "POST", f"/devices/{device.device_id}/commands",
                          json={"name": "relay_set", "args": {"on": True}})
    assert r.status_code == 200 and r.json() == {"on": True}
    assert device.actuator_state("relay")["on"] is True

    # 6. Đổi chu kỳ gửi → thiết bị lưu và gửi lại meta
    r = await system.call("operator", "PUT", f"/devices/{device.device_id}/interval", json={"seconds": 30})
    assert r.json() == {"interval_s": 30}
    await system.broker.settle()
    assert device.identity.state["interval_s"] == 30
    assert (await system.call("viewer", "GET", f"/devices/{device.device_id}")).json()["interval_s"] == 30

    # 7. Khởi động lại từ xa → báo offline lý do reboot → lên lại
    assert (await system.call("operator", "POST", f"/devices/{device.device_id}/reboot")).status_code == 200
    await system.broker.settle()
    assert (await system.call("viewer", "GET", f"/devices/{device.device_id}")).json()["online"] is False
    await device.go_online()
    assert (await system.call("viewer", "GET", f"/devices/{device.device_id}")).json()["online"] is True

    # 8. Mất điện đột ngột → broker phát Last Will → backend thấy offline
    await device.power_loss()
    assert (await system.call("viewer", "GET", f"/devices/{device.device_id}")).json()["online"] is False
    await device.go_online()

    # 9. Thu hồi → xóa tài khoản MQTT, xóa tin retained, thiết bị không đăng nhập lại được
    assert (await system.call("admin", "DELETE", f"/devices/{device.device_id}")).status_code == 200
    await system.broker.settle()
    assert device.device_id not in system.broker.accounts
    assert p.device_topic(device.device_id, p.STATUS) not in system.broker.retained
    assert (await system.call("admin", "GET", f"/devices/{device.device_id}")).status_code == 404
    try:
        await device.go_online()
        raise AssertionError("thiết bị đã thu hồi vẫn đăng nhập được")
    except ConnectionError:
        pass

    actions = system.audit_actions()
    for action in ("registration.approve", "device.barn.update", "device.interval.update", "device.revoke"):
        assert action in actions


async def test_tc21_tu_choi_dang_ky(system):
    device = system.new_device()
    await device.request_provisioning()
    r = await system.call("admin", "POST", f"/registrations/{device.hw_id}/reject", json={"reason": "không rõ nguồn gốc"})
    assert r.status_code == 200
    await system.broker.settle()
    assert device.provision_replies[-1] == {"status": "rejected", "reason": "không rõ nguồn gốc"}
    assert device.device_id is None
    assert p.default_device_id(device.hw_id) not in system.broker.accounts


async def test_tc22_gui_lai_yeu_cau_khong_tao_ban_ghi_trung(system):
    device = system.new_device()
    for _ in range(3):  # firmware gửi lại mỗi 10 s khi chưa được duyệt
        await device.request_provisioning()
    rows = [r for r in (await system.call("admin", "GET", "/registrations")).json() if r["hw_id"] == device.hw_id]
    assert len(rows) == 1
    assert [reply["status"] for reply in device.provision_replies] == ["pending"] * 3


async def test_tc23_thiet_bi_da_duyet_xin_lai_thi_phai_duyet_lai(system):
    """Flash bị xóa (hoặc kẻ gian giả hw_id): không được tự cấp lại quyền."""
    device = await system.online_device()
    impostor = system.new_device(hw_id=device.hw_id)  # cùng hw_id, mật khẩu khác
    await impostor.request_provisioning()
    assert impostor.provision_replies[-1]["status"] == "pending"
    assert impostor.device_id is None
    # Tài khoản MQTT cũ vẫn giữ mật khẩu của thiết bị thật
    assert system.broker.accounts[device.device_id].password == device.password


async def test_tc24_telemetry_luu_lich_su_dung_thu_tu(system):
    device = await system.online_device()
    for t in (28.0, 29.5, 31.0, 32.5):
        await device.send_telemetry({"room": {"temperature": t, "humidity": 65}})
    r = await system.call("viewer", "GET", f"/devices/{device.device_id}/telemetry", params={"limit": 10})
    temps = sorted(row["readings"]["values"]["room"]["temperature"] for row in r.json())
    assert temps == [28.0, 29.5, 31.0, 32.5]
    with system.db() as db:
        assert db.query(models.Telemetry).filter_by(device_id=device.device_id).count() == 4


async def test_tc25_telemetry_ghi_loi_cam_bien(system):
    """Cảm biến hỏng: firmware gửi `errors`, backend lưu lại để hiển thị."""
    device = await system.online_device()
    device.ctx.publish(p.TELEMETRY, {"readings": {}, "errors": {"room": "timeout"}})
    await system.broker.settle()
    latest = (await system.call("viewer", "GET", f"/devices/{device.device_id}/telemetry/latest")).json()
    assert latest["readings"]["errors"] == {"room": "timeout"}


async def test_tc26_backend_khoi_dong_lai_van_biet_thiet_bi_online(system):
    """Trạng thái online giữ bằng tin retained: backend kết nối lại đọc được ngay."""
    device = await system.online_device()
    await system.gateway.transport.stop()
    await system.gateway.transport.start()  # _connection_changed: đánh dấu offline hết
    for topic in p.BACKEND_SUBSCRIPTIONS:
        await system.gateway.transport.subscribe(topic, system.gateway._message)
    await system.broker.settle()
    assert (await system.call("viewer", "GET", f"/devices/{device.device_id}")).json()["online"] is True


async def test_tc27_doc_cam_bien_theo_yeu_cau(system):
    device = await system.online_device()
    r = await system.call("viewer", "GET", f"/devices/{device.device_id}/readings")
    assert r.status_code == 200
    room = r.json()["values"]["room"]
    assert set(room) == {"temperature", "humidity"} and -10 <= room["temperature"] <= 50
    # Cảm biến không tồn tại → mã lỗi của firmware
    r = await system.call("viewer", "GET", f"/devices/{device.device_id}/sensors/khong-co")
    assert r.status_code == 502 and r.json()["code"] == "sensor_not_found"
    assert json.loads(device.sent[-1][1])["data"]["ok"] is False
