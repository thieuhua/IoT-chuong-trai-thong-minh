"""TC-50..TC-66: kiểm thử bảo mật (đề bài yêu cầu ít nhất 2).

Ba lớp: (1) API: JWT, mật khẩu, lộ dữ liệu; (2) broker MQTT: mỗi thiết bị một tài
khoản + ACL do backend tạo khi duyệt; (3) xử lý tin MQTT giả mạo / hỏng.
Lớp (2) chạy trên broker giả lập Dynamic Security; test_09 kiểm lại trên Mosquitto thật.
"""
from __future__ import annotations

import base64
from datetime import timedelta
import json

import jwt
import pytest

from app import models
from app.services import auth
from conftest import PASSWORD, token_for
from iot_core import protocol as p
from support.broker import NotAuthorised


# ---------------------------------------------------------------- (1) API
async def test_tc50_mat_khau_luu_dang_bcrypt(system):
    with system.db() as db:
        for user in db.query(models.User):
            assert user.password_hash.startswith("$2b$12$")  # bcrypt, cost 12
            assert PASSWORD not in user.password_hash


@pytest.mark.parametrize("make_header", [
    lambda s: {},                                                    # không có token
    lambda s: {"Authorization": "Bearer abc.def.ghi"},               # token rác
    lambda s: {"Authorization": "Bearer " + token_for(s.users["admin"], minutes=-1)},  # hết hạn
    lambda s: {"Authorization": "Bearer " + token_for(s.users["admin"], token_type="refresh")},
    lambda s: {"Authorization": "Bearer " + jwt.encode(
        {"sub": s.users["admin"], "type": "access"}, "doan-mo-khoa-sai-" + "y" * 32, algorithm="HS256")},
    lambda s: {"Authorization": "Bearer " + _alg_none(s.users["admin"])},
], ids=["khong-token", "token-rac", "het-han", "refresh-thay-access", "sai-khoa-ky", "alg-none"])
async def test_tc51_token_khong_hop_le_bi_tu_choi(system, make_header):
    r = await system.client.get("/users", headers=make_header(system))
    assert r.status_code in (401, 403)
    assert r.status_code != 200


def _alg_none(user_id):
    def b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': user_id, 'type': 'access'})}."


async def test_tc52_sua_vai_tro_trong_token_khong_leo_quyen(system):
    """Vai trò đọc từ DB theo `sub`, không tin vào nội dung token."""
    payload = jwt.decode(system.tokens["viewer"], options={"verify_signature": False})
    payload["role"] = "Admin"
    forged = jwt.encode(payload, auth.SECRET_KEY, algorithm="HS256")  # kể cả khi ký đúng
    r = await system.client.get("/users", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 403


@pytest.mark.parametrize("username", ["admin' OR '1'='1", "admin\"; DROP TABLE users; --", "' UNION SELECT 1 --"])
async def test_tc53_chen_sql_vao_dang_nhap_khong_tac_dung(system, username):
    r = await system.client.post("/auth/login", json={"username": username, "password": "x' OR '1'='1"})
    assert r.status_code == 401
    with system.db() as db:
        assert db.query(models.User).count() == 4


async def test_tc54_api_khong_tra_mat_khau_hay_hash(system):
    device = system.new_device()
    await device.request_provisioning()
    responses = [await system.call("admin", "GET", "/registrations", params={"status": "all"}),
                 await system.call("admin", "GET", "/users")]
    await system.approve_via_api(device.hw_id)
    await device.go_online()
    responses += [await system.call("admin", "GET", "/devices"),
                  await system.call("admin", "GET", "/barns/barn-1/users")]
    for r in responses:
        text = r.text
        assert r.status_code == 200
        assert "password" not in text and "$2b$" not in text and device.password not in text


async def test_tc55_mat_khau_thiet_bi_khong_luu_lai_sau_khi_duyet(system):
    device = system.new_device()
    await device.request_provisioning()
    await system.approve_via_api(device.hw_id)
    with system.db() as db:
        row = db.get(models.Registration, device.hw_id)
        assert row.password is None  # chỉ broker giữ mật khẩu (Dynamic Security)


# ------------------------------------------------- (2) broker: tài khoản + ACL
@pytest.fixture
async def two_devices(system):
    return await system.online_device("barn-1"), await system.online_device("barn-2")


async def test_tc56_thiet_bi_a_khong_gia_mao_du_lieu_thiet_bi_b(system, two_devices):
    a, b = two_devices
    fake = a.ctx.encode(p.TELEMETRY, {"readings": {"room": {"temperature": 99, "humidity": 1}}})
    accepted = system.broker.publish(a.session, b.topic(p.TELEMETRY), fake)
    await system.broker.settle()
    assert accepted is False
    assert (a.device_id, "publish", b.topic(p.TELEMETRY)) in system.broker.denied
    r = await system.call("admin", "GET", f"/devices/{b.device_id}/telemetry/latest")
    assert r.json() is None  # backend không nhận được gì


async def test_tc57_thiet_bi_a_khong_nghe_lenh_cua_thiet_bi_b(system, two_devices):
    a, b = two_devices
    for topic in (b.topic(p.CMD), "iot/v1/+/cmd", "iot/v1/#", "#"):
        assert system.broker.subscribe(a.session, topic, lambda *_: None) is False, topic


async def test_tc58_thiet_bi_khong_gui_duoc_lenh_cho_chinh_minh(system, two_devices):
    """Chỉ backend được publish `cmd` (OTA cũng dựa vào điều này)."""
    a, _ = two_devices
    assert system.broker.publish(a.session, a.topic(p.CMD), b"{}") is False


async def test_tc59_bootstrap_khong_doc_duoc_yeu_cau_dang_ky_chua_mat_khau(system):
    attacker = system.broker.connect("deadbeef0000", "bootstrap", "bootstrap-pw")
    assert system.broker.subscribe(attacker, "iot/v1/provision/+/request", lambda *_: None) is False
    assert system.broker.subscribe(attacker, "iot/v1/+/telemetry", lambda *_: None) is False
    assert system.broker.publish(attacker, "iot/v1/esp32-aaaaaaaaaaaa/telemetry", b"{}") is False


async def test_tc60_sai_mat_khau_hoac_doi_client_id_bi_tu_choi(system, two_devices):
    a, b = two_devices
    with pytest.raises(NotAuthorised):
        system.broker.connect(a.device_id, a.device_id, "sai-mat-khau")
    with pytest.raises(NotAuthorised):  # dùng mật khẩu đúng nhưng client id khác (ghim client id)
        system.broker.connect("may-khac", a.device_id, a.password)
    with pytest.raises(NotAuthorised):  # mật khẩu thiết bị A không mở được tài khoản B
        system.broker.connect(b.device_id, b.device_id, a.password)


async def test_tc61_backend_cap_quyen_toi_thieu_khi_duyet(system):
    device = system.new_device()
    await device.request_provisioning()
    await system.approve_via_api(device.hw_id)
    role = system.broker.roles[f"dev-{device.device_id}"]
    assert sorted((acl["acltype"], acl["topic"]) for acl in role) == sorted(
        [("publishClientSend", f"iot/v1/{device.device_id}/{leaf}") for leaf in ("status", "meta", "telemetry", "resp")]
        + [("subscribeLiteral", f"iot/v1/{device.device_id}/cmd")])
    assert not any("+" in acl["topic"] or "#" in acl["topic"] for acl in role)


# --------------------------------------------- (3) tin MQTT giả mạo / hỏng
async def test_tc62_phan_hoi_gia_tu_thiet_bi_khac_bi_bo_qua(system, two_devices):
    """B đọc trộm được id lệnh gửi A rồi tự trả lời ok trên topic của B: backend phải bỏ qua."""
    a, b = two_devices
    a.silent = True

    def forge(topic, payload):
        cmd = json.loads(payload)
        system.broker.publish(b.session, b.topic(p.RESP),
                              b.ctx.encode(p.RESP, {"re": cmd["id"], "ok": True, "result": {"on": True}}))
    system.broker.sessions["backend"].handlers.append((a.topic(p.CMD), forge))  # giả định kẻ gian thấy lệnh
    r = await system.call("operator", "POST", f"/devices/{a.device_id}/commands",
                          json={"name": "relay_set", "args": {"on": True}, "timeout_s": 0.3})
    assert r.status_code == 504


@pytest.mark.parametrize("payload", [
    b"khong phai json",
    b"[1,2,3]",
    json.dumps({"v": 2, "id": "1-1", "ts": None, "type": "telemetry", "data": {}}).encode(),
    json.dumps({"v": 1, "id": "1-1", "ts": None, "type": "status", "data": {}}).encode(),  # sai type
    b"{" + b" " * 5000 + b"}",                                                               # > 4096 byte
], ids=["khong-json", "mang", "sai-phien-ban", "sai-type", "qua-lon"])
async def test_tc63_tin_hong_bi_bo_qua_he_thong_van_chay(system, payload):
    device = await system.online_device()
    system.broker.publish(device.session, device.topic(p.TELEMETRY), payload)
    await system.broker.settle()
    assert (await system.call("admin", "GET", f"/devices/{device.device_id}/telemetry/latest")).json() is None
    r = await system.call("operator", "POST", f"/devices/{device.device_id}/commands", json={"name": "ping"})
    assert r.status_code == 200


async def test_tc64_thiet_bi_da_thu_hoi_khong_quay_lai_tu_tin_retained(system):
    device = await system.online_device()
    await system.call("admin", "DELETE", f"/devices/{device.device_id}")
    await system.broker.settle()
    for leaf in (p.STATUS, p.META):
        assert device.topic(leaf) not in system.broker.retained
    with pytest.raises(NotAuthorised):
        system.broker.connect(device.device_id, device.device_id, device.password)


# ------------------------------------------- lỗ hổng còn lại (chưa sửa trong code)
@pytest.mark.xfail(reason="P2: /camera/* chưa yêu cầu đăng nhập (backend/app/main.py). "
                          "Thêm Depends(get_current_user) rồi xóa dòng xfail này.", strict=False)
@pytest.mark.parametrize("method,path", [("GET", "/camera/status"), ("POST", "/camera/stop"),
                                         ("POST", "/camera/config")])
async def test_tc65_camera_phai_dang_nhap(system, method, path):
    r = await system.client.request(method, path, json={})
    assert r.status_code in (401, 403)


@pytest.mark.xfail(reason="Đọc thiết bị/telemetry (GET /devices/...) chỉ cần đăng nhập, chưa kiểm "
                          "chuồng: Operator chuồng 2 xem được dữ liệu chuồng 1.", strict=False)
async def test_tc66_khong_xem_duoc_du_lieu_chuong_khong_duoc_gan(system):
    device = await system.online_device("barn-1")
    await device.send_telemetry()
    for path in (f"/devices/{device.device_id}", f"/devices/{device.device_id}/telemetry/latest"):
        assert (await system.call("operator2", "GET", path)).status_code == 403
