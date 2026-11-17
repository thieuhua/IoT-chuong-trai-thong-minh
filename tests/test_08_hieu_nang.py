"""TC-80..TC-86: kiểm thử phi chức năng có số đo.

Số liệu ghi ra tests/ket-qua/so-do-moi-nhat.md (và .json) để dán vào báo cáo.
Chạy trên một máy, broker trong bộ nhớ: đo phần mềm (API + gateway + DB + firmware),
chưa gồm Wi-Fi. Số đo qua Mosquitto thật nằm ở test_09. Ngưỡng đặt rộng để máy
yếu vẫn đạt; mục tiêu thật của đề tài: lệnh < 2 s, chu kỳ telemetry 10 s.
"""
from __future__ import annotations

import asyncio
import statistics
import time

import pytest

from app import models
from conftest import PASSWORD

pytestmark = pytest.mark.hieu_nang


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q / 100 * (len(values) - 1))))]


def ms(seconds):
    return seconds * 1000


async def test_tc80_thoi_gian_phan_hoi_api_doc(system, do_luong):
    device = await system.online_device("barn-1")
    for _ in range(20):
        await device.send_telemetry()
    times = []
    for path in ("/barns", f"/devices/{device.device_id}/telemetry/latest",
                 f"/devices/{device.device_id}/telemetry?limit=20"):
        for _ in range(100):
            started = time.perf_counter()
            r = await system.call("viewer", "GET", path)
            times.append(time.perf_counter() - started)
            assert r.status_code == 200
    p95 = ms(pct(times, 95))
    do_luong("API đọc (GET, 300 lần): trung vị", ms(statistics.median(times)), "ms")
    do_luong("API đọc (GET, 300 lần): p95", p95, "ms", nguong="≤ 200 ms", dat=p95 <= 200)
    assert p95 <= 200


async def test_tc81_do_tre_lenh_dieu_khien_khu_hoi(system, do_luong):
    """API → backend → MQTT → firmware bật/tắt relay → resp → API trả về."""
    device = await system.online_device("barn-1")
    times = []
    for i in range(200):
        started = time.perf_counter()
        r = await system.call("operator", "POST", f"/devices/{device.device_id}/commands",
                              json={"name": "relay_set", "args": {"on": i % 2 == 0}})
        times.append(time.perf_counter() - started)
        assert r.status_code == 200
    p95 = ms(pct(times, 95))
    do_luong("Lệnh relay khứ hồi (200 lần): trung vị", ms(statistics.median(times)), "ms")
    do_luong("Lệnh relay khứ hồi (200 lần): p95", p95, "ms", nguong="≤ 300 ms", dat=p95 <= 300,
             ghi_chu="không gồm Wi-Fi")
    assert p95 <= 300


async def test_tc82_thong_luong_telemetry_khong_mat_ban_tin(system, do_luong):
    devices = [await system.online_device("barn-1") for _ in range(5)]
    per_device = 100
    started = time.perf_counter()
    for i in range(per_device):
        for device in devices:
            device.ctx.publish("telemetry", {"readings": {"room": {"temperature": 25 + i % 10, "humidity": 60}}})
    await system.broker.settle(rounds=5000)
    elapsed = time.perf_counter() - started
    total = per_device * len(devices)
    with system.db() as db:
        stored = db.query(models.Telemetry).count()
    rate = total / elapsed
    # Nhu cầu thật: 5 chuồng × 1 bản tin / 10 s = 0,5 bản tin/s
    do_luong("Thông lượng ghi telemetry (5 thiết bị × 100 bản tin)", rate, "bản tin/s",
             nguong="≥ 50 (cần 0,5)", dat=rate >= 50)
    do_luong("Bản tin telemetry bị mất", total - stored, "bản tin", nguong="0", dat=stored == total)
    assert stored == total and rate >= 50


async def test_tc83_lenh_dong_thoi_nhieu_chuong(system, do_luong):
    """100 lệnh tới 5 thiết bị, tối đa 10 lệnh cùng lúc (vd. 10 người bấm cùng lúc)."""
    devices = [await system.online_device("barn-1") for _ in range(5)]
    for d in devices:
        d.reply_delay_s = 0.05  # giả lập thiết bị xử lý mất 50 ms
    limit = asyncio.Semaphore(10)

    async def one(d, i):
        async with limit:
            return await send(d, i)

    async def send(d, i):
        started = time.perf_counter()
        r = await system.call("admin", "POST", f"/devices/{d.device_id}/commands",
                              json={"name": "servo_set", "args": {"angle": (i * 10) % 180}})
        return r.status_code, time.perf_counter() - started

    started = time.perf_counter()
    results = await asyncio.gather(*(one(d, i) for d in devices for i in range(20)))
    total = time.perf_counter() - started
    ok = sum(1 for status, _ in results if status == 200)
    worst = ms(max(t for _, t in results))
    do_luong("100 lệnh, 10 lệnh cùng lúc, 5 thiết bị: thành công", ok, "/100", nguong="100/100", dat=ok == 100)
    do_luong("100 lệnh (10 cùng lúc): lâu nhất", worst, "ms", nguong="≤ 2000 ms", dat=worst <= 2000)
    do_luong("100 lệnh (10 cùng lúc): tổng thời gian", ms(total), "ms")
    assert ok == 100 and worst <= 2000


async def test_tc84_thoi_gian_bao_het_gio_dung_cau_hinh(system, do_luong):
    device = await system.online_device("barn-1")
    device.silent = True
    started = time.perf_counter()
    r = await system.call("operator", "POST", f"/devices/{device.device_id}/commands",
                          json={"name": "ping", "timeout_s": 1})
    elapsed = time.perf_counter() - started
    assert r.status_code == 504
    do_luong("Báo hết giờ khi thiết bị im lặng (cấu hình 1 s)", elapsed, "s",
             nguong="1,0 – 1,5 s", dat=1.0 <= elapsed <= 1.5)
    assert 1.0 <= elapsed <= 1.5


async def test_tc85_dang_nhap_bcrypt(system, do_luong):
    """bcrypt chậm có chủ đích: đủ nhanh cho người dùng, đủ chậm để dò mật khẩu tốn kém."""
    times = []
    for _ in range(5):
        started = time.perf_counter()
        r = await system.client.post("/auth/login", json={"username": "viewer", "password": PASSWORD})
        times.append(time.perf_counter() - started)
        assert r.status_code == 200
    mean = ms(statistics.mean(times))
    do_luong("Đăng nhập (bcrypt cost 12), trung bình 5 lần", mean, "ms", nguong="50 – 1500 ms",
             dat=50 <= mean <= 1500)
    do_luong("Số lần thử mật khẩu tối đa / giây / lõi CPU", 1000 / mean, "lần/s",
             ghi_chu="càng nhỏ càng khó dò mật khẩu")
    assert 50 <= mean <= 1500


async def test_tc86_dang_ky_den_online(system, do_luong):
    started = time.perf_counter()
    for _ in range(10):
        await system.online_device("barn-1")
    each = ms((time.perf_counter() - started) / 10)
    do_luong("Đăng ký → duyệt → online (trung bình 10 thiết bị)", each, "ms",
             ghi_chu="không gồm thời gian admin bấm duyệt")
    rows = (await system.call("admin", "GET", "/devices", params={"online": "true"})).json()
    assert len(rows) == 10


@pytest.mark.xfail(reason="Mỗi request lệnh giữ 1 kết nối DB trong lúc chờ ESP32 trả lời. Pool mặc định "
                          "5 + 10 kết nối: > 15 lệnh cùng lúc thì backend nghẽn (chờ pool 30 s rồi lỗi). "
                          "Sửa: đóng session DB trước khi await gateway, hoặc tăng pool_size.",
                   strict=False)
async def test_tc87_40_lenh_cung_luc_khong_nghen(system, do_luong):
    devices = [await system.online_device("barn-1") for _ in range(4)]
    for d in devices:
        d.reply_delay_s = 0.2
    started = time.perf_counter()
    results = await asyncio.gather(*(
        system.call("admin", "POST", f"/devices/{d.device_id}/commands",
                    json={"name": "ping", "timeout_s": 5})
        for d in devices for _ in range(10)), return_exceptions=True)
    elapsed = time.perf_counter() - started
    ok = sum(1 for r in results if not isinstance(r, Exception) and r.status_code == 200)
    do_luong("40 lệnh cùng lúc (không giới hạn): thành công", ok, "/40", nguong="40/40", dat=ok == 40,
             ghi_chu=f"lỗi đã biết (xfail): mất {elapsed:.1f} s, nghẽn pool kết nối DB" if ok < 40 else "")
    assert ok == 40
