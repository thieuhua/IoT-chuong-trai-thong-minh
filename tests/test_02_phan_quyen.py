"""TC-10..TC-16: phân quyền 3 vai trò (Admin / Operator / Viewer) + phân quyền theo chuồng.

Bảng quyền đang có trong code (backend/app/main.py):
- Admin: mọi thứ.
- Operator: điều khiển thiết bị trong chuồng được gán, xử lý cảnh báo, hẹn giờ.
- Viewer: chỉ xem chuồng được gán.
`operator2` là Operator của chuồng 2, dùng để kiểm tra không chạm được chuồng 1.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

ROLES = ("admin", "operator", "viewer", "operator2")


@pytest.fixture
async def device(system):
    return await system.online_device("barn-1")


def schedule_body(device_id):
    return {"device_id": device_id, "command_name": "relay_set", "args": {"on": True},
            "run_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}


# (tên, phương thức, đường dẫn, body, mã mong đợi theo admin/operator/viewer/operator2)
MATRIX = [
    ("gửi lệnh relay", "POST", "/devices/{dev}/commands", {"name": "relay_set", "args": {"on": True}},
     (200, 200, 403, 403)),
    ("ping thiết bị", "POST", "/devices/{dev}/ping", None, (200, 200, 403, 403)),
    ("đổi chu kỳ gửi", "PUT", "/devices/{dev}/interval", {"seconds": 5}, (200, 200, 403, 403)),
    ("đổi tên thiết bị", "PATCH", "/devices/{dev}", {"name": "ESP32 chuồng 1"}, (200, 200, 403, 403)),
    ("xem thiết bị của chuồng", "GET", "/barns/barn-1/devices", None, (200, 200, 200, 403)),
    ("xem người được gán", "GET", "/barns/barn-1/assignments", None, (200, 200, 200, 403)),
    ("tạo lịch hẹn", "POST", "/barns/barn-1/scheduled-events", "schedule", (201, 201, 403, 403)),
    ("xem lịch hẹn", "GET", "/barns/barn-1/scheduled-events", None, (200, 200, 200, 403)),
    ("tạo chuồng", "POST", "/barns", {"name": "Chuồng mới"}, (201, 403, 403, 403)),
    ("gán người vào chuồng", "PUT", "/barns/barn-2/assignments",
     {"assignments": [{"user_id": "{viewer_id}", "access_level": "Viewer"}]}, (200, 403, 403, 403)),
    ("gán thiết bị vào chuồng", "PUT", "/devices/{dev}/barn", {"barn_id": "barn-1"}, (200, 403, 403, 403)),
    ("danh sách người dùng", "GET", "/users", None, (200, 403, 403, 403)),
    ("tạo người dùng", "POST", "/users", {"username": "u-{role}", "password": "MatKhau@123"},
     (201, 403, 403, 403)),
    ("xem nhật ký audit", "GET", "/audit-logs", None, (200, 403, 403, 403)),
]


@pytest.mark.parametrize("role_index,role", list(enumerate(ROLES)))
@pytest.mark.parametrize("name,method,path,body,expected", MATRIX, ids=[row[0] for row in MATRIX])
async def test_tc10_ma_tran_phan_quyen(system, device, role_index, role, name, method, path, body, expected):
    def fill(value):
        if isinstance(value, str):
            return (value.replace("{dev}", device.device_id).replace("{role}", role)
                    .replace("{viewer_id}", system.users["viewer"]))
        if isinstance(value, dict):
            return {k: fill(v) for k, v in value.items()}
        if isinstance(value, list):
            return [fill(v) for v in value]
        return value
    payload = schedule_body(device.device_id) if body == "schedule" else fill(body)
    r = await system.call(role, method, fill(path), json=payload)
    assert r.status_code == expected[role_index], f"{name} / {role}: {r.status_code} {r.text}"


async def test_tc11_viewer_bi_chan_khong_lam_thay_doi_thiet_bi(system, device):
    """Lệnh bị 403 thì không có gì được gửi xuống ESP32."""
    before = len([t for _, t, _ in system.broker.log if t.endswith("/cmd")])
    r = await system.call("viewer", "POST", f"/devices/{device.device_id}/commands",
                          json={"name": "relay_set", "args": {"on": True}})
    assert r.status_code == 403
    await system.broker.settle()
    assert len([t for _, t, _ in system.broker.log if t.endswith("/cmd")]) == before
    assert device.actuator_state("relay")["on"] is False


async def test_tc12_moi_nguoi_chi_thay_chuong_duoc_gan(system):
    seen = {}
    for role in ROLES:
        r = await system.call(role, "GET", "/barns")
        assert r.status_code == 200
        seen[role] = sorted(b["id"] for b in r.json())
    assert seen == {"admin": ["barn-1", "barn-2"], "operator": ["barn-1"],
                    "viewer": ["barn-1"], "operator2": ["barn-2"]}


async def test_tc13_chi_admin_duyet_hoac_tu_choi_thiet_bi(system):
    device = system.new_device()
    await device.request_provisioning()
    for role in ("operator", "viewer"):
        assert (await system.call(role, "POST", f"/registrations/{device.hw_id}/approve", json={})).status_code == 403
        assert (await system.call(role, "POST", f"/registrations/{device.hw_id}/reject", json={})).status_code == 403
    assert device.device_id is None


async def test_tc14_thiet_bi_chua_gan_chuong_operator_khong_dieu_khien_duoc(system):
    device = await system.online_device(barn_id=None)
    r = await system.call("operator", "POST", f"/devices/{device.device_id}/commands",
                          json={"name": "relay_set", "args": {"on": True}})
    assert r.status_code == 409
    r = await system.call("admin", "POST", f"/devices/{device.device_id}/commands",
                          json={"name": "relay_set", "args": {"on": True}})
    assert r.status_code == 200


async def test_tc15_bo_gan_chuong_thi_mat_quyen_ngay(system, device):
    url = f"/devices/{device.device_id}/commands"
    body = {"name": "relay_set", "args": {"on": False}}
    assert (await system.call("operator", "POST", url, json=body)).status_code == 200
    r = await system.call("admin", "DELETE", "/barns/barn-1/assignments", json={"user_id": system.users["operator"]})
    assert r.status_code == 200
    assert (await system.call("operator", "POST", url, json=body)).status_code == 403


async def test_tc16_viewer_khong_xu_ly_canh_bao(system):
    # Cảnh báo không tồn tại: Viewer bị chặn trước (403), Operator đi tiếp tới 404.
    assert (await system.call("viewer", "POST", "/alerts/khong-co/ack", json={})).status_code == 403
    assert (await system.call("operator", "POST", "/alerts/khong-co/ack", json={})).status_code == 404
