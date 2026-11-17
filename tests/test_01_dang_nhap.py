"""TC-01..TC-08: đăng nhập, phiên làm việc, quản lý tài khoản (API thật + DB)."""
from __future__ import annotations

import pytest

from app import models
from conftest import PASSWORD


async def login(system, username, password=PASSWORD):
    return await system.client.post("/auth/login", json={"username": username, "password": password})


async def test_tc01_dang_nhap_dung_tra_token_va_vai_tro(system):
    r = await login(system, "operator")
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["access_token"] and body["refresh_token"]
    assert body["user"]["role"] == "Operator"
    # Token vừa cấp dùng được ngay
    me = await system.client.get("/barns", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert "auth.login" in system.audit_actions()


@pytest.mark.parametrize("username,password", [
    ("operator", "SaiMatKhau123"),
    ("khong-ton-tai", PASSWORD),
])
async def test_tc02_sai_mat_khau_hoac_tai_khoan_bi_401_cung_mot_thong_bao(system, username, password):
    r = await login(system, username, password)
    assert r.status_code == 401
    # Không tiết lộ là sai tên hay sai mật khẩu
    assert r.json()["detail"] == "Invalid username or password"


async def test_tc03_tai_khoan_bi_khoa_khong_dang_nhap_duoc(system):
    system.add_user("bi-khoa", "Viewer", status="locked")
    assert (await login(system, "bi-khoa")).status_code == 403


async def test_tc04_refresh_cap_token_moi_va_vo_hieu_token_cu(system):
    tokens = (await login(system, "viewer")).json()
    r = await system.client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    new = r.json()
    assert new["refresh_token"] != tokens["refresh_token"]
    # Dùng lại refresh token cũ (bị đánh cắp) phải bị từ chối
    again = await system.client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert again.status_code == 401


async def test_tc05_dang_xuat_thu_hoi_refresh_token(system):
    tokens = (await login(system, "viewer")).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    r = await system.client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=headers)
    assert r.status_code == 200
    r = await system.client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401


async def test_tc06_doi_mat_khau_thu_hoi_moi_phien(system):
    tokens = (await login(system, "operator")).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    r = await system.client.put("/me/password", headers=headers,
                                json={"old_password": "sai-mat-khau", "new_password": "MatKhauMoi@456"})
    assert r.status_code == 400
    r = await system.client.put("/me/password", headers=headers,
                                json={"old_password": PASSWORD, "new_password": "MatKhauMoi@456"})
    assert r.status_code == 200
    assert (await system.client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})).status_code == 401
    assert (await login(system, "operator")).status_code == 401
    assert (await login(system, "operator", "MatKhauMoi@456")).status_code == 200


async def test_tc07_admin_tao_va_khoa_nguoi_dung(system):
    r = await system.call("admin", "POST", "/users",
                          json={"username": "nhanvien", "password": "MatKhau@789", "role": "Viewer"})
    assert r.status_code == 201
    user_id = r.json()["id"]
    assert (await system.call("admin", "POST", "/users",
                              json={"username": "nhanvien", "password": "MatKhau@789"})).status_code == 409
    assert (await login(system, "nhanvien", "MatKhau@789")).status_code == 200
    r = await system.call("admin", "PATCH", f"/users/{user_id}", json={"status": "locked"})
    assert r.status_code == 200 and r.json()["status"] == "locked"
    assert (await login(system, "nhanvien", "MatKhau@789")).status_code == 403
    # Admin không tự khóa chính mình
    r = await system.call("admin", "PATCH", f"/users/{system.users['admin']}", json={"status": "locked"})
    assert r.status_code == 400
    actions = system.audit_actions()
    assert "user.create" in actions and "user.update" in actions


async def test_tc08_tai_khoan_bi_khoa_thi_token_dang_dung_mat_hieu_luc(system):
    with system.db() as db:
        db.query(models.User).filter(models.User.id == system.users["viewer"]).update({"status": "locked"})
        db.commit()
    assert (await system.call("viewer", "GET", "/barns")).status_code == 401


@pytest.mark.parametrize("body", [
    {"username": "ab", "password": PASSWORD},                # tên quá ngắn
    {"username": "operator", "password": "ngan"},            # mật khẩu < 8 ký tự
    {"username": "operator", "password": "x" * 73},          # > 72 byte (giới hạn bcrypt)
])
async def test_tc08b_du_lieu_dang_nhap_khong_hop_le_bi_422(system, body):
    assert (await system.client.post("/auth/login", json=body)).status_code == 422
