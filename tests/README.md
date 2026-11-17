# Kiểm thử hệ thống (tests/)

Bộ test này kiểm tra **cả hệ thống ghép lại** theo code mới nhất của repo:
API FastAPI (đăng nhập JWT, 3 vai trò, chuồng) → `DeviceGateway` → MQTT `iot/v1/...`
→ **code firmware thật** trong `firmware/src` (relay, servo, cảm biến, xử lý lệnh) → phản hồi `resp`.

Test riêng từng phần vẫn nằm ở `backend/tests/` và `firmware/tests/`.

## Chạy

Không cần Docker, MySQL hay ESP32. Python 3.11 trở lên.

```powershell
python -m pip install -r tests/requirements.txt
python -m pytest tests            # khoảng 2 phút
python -m pytest tests -m "not hieu_nang"   # bỏ phần đo hiệu năng, chạy nhanh hơn
```

Kết quả mong đợi hiện tại: **147 passed, 10 xfailed** (6 test broker thật bị *skipped* nếu không có broker).

Số đo hiệu năng của lần chạy gần nhất được ghi vào `tests/ket-qua/so-do-moi-nhat.md`
(bảng dán thẳng vào chương kiểm thử). Bản chạy mẫu: [ket-qua/so-do-2026-11-17.md](ket-qua/so-do-2026-11-17.md).
Nên chạy lại trên máy của nhóm (và với broker thật) trước khi đưa số vào báo cáo.

### Chạy thêm phần broker thật (test_09)

```powershell
docker compose -f deployment/compose.yaml up -d --wait
python -m pytest tests/test_09_broker_that.py
```

Test đọc mật khẩu từ `deployment/.env` (đổi bằng biến `IOT_TEST_ENV_FILE`). Thiết bị test có `hw_id`
bắt đầu bằng `7e57` và tự được xóa khỏi broker sau khi chạy.

## Cách dựng môi trường test

| Thành phần | Trong test | Ghi chú |
| --- | --- | --- |
| Backend | `backend/app/main.py` thật, gọi qua HTTP (httpx) | Không mock quyền: token JWT thật, DB thật |
| Cơ sở dữ liệu | Model SQLAlchemy của backend trên SQLite (file tạm) | Dùng `MySQLDeviceRegistry` / `MySQLTelemetryStore` như khi có `DATABASE_URL` |
| Broker MQTT | `support/broker.py`: broker trong bộ nhớ | Có Dynamic Security giống Mosquitto 2.0 (tài khoản, ACL, lỗi trả về), retained, Last Will |
| ESP32 | `support/device.py`: chạy `App` + `commands.dispatch` của firmware | Chỉ thay Wi-Fi/umqtt; thứ tự đăng ký/kết nối theo `provisioning.py` và `session.py` |

## Danh sách test

| File | Mã | Nội dung | Loại |
| --- | --- | --- | --- |
| `test_01_dang_nhap.py` | TC-01..08 | Đăng nhập, refresh xoay vòng, đăng xuất, đổi mật khẩu thu hồi phiên, khóa tài khoản | Chức năng |
| `test_02_phan_quyen.py` | TC-10..16 | Ma trận 14 thao tác × 4 tài khoản (Admin, Operator, Viewer, Operator chuồng khác) | Chức năng + bảo mật |
| `test_03_vong_doi_thiet_bi.py` | TC-20..27 | Đăng ký → duyệt → online → telemetry → lệnh → đổi chu kỳ → reboot → mất điện (LWT) → thu hồi | Chức năng |
| `test_04_lenh_dieu_khien.py` | TC-30..39 | Relay (quạt), servo (máng ăn), mã lỗi firmware, hết giờ 504, offline 409, nhiều lệnh song song | Chức năng |
| `test_05_canh_bao_lich_hen.py` | TC-40..47 | Xem/xác nhận/đóng cảnh báo, lịch hẹn chạy lệnh xuống ESP32, lặp hằng ngày, audit log | Chức năng |
| `test_06_bao_mat.py` | TC-50..66 | JWT giả/hết hạn/`alg:none`, SQL injection, không lộ mật khẩu, ACL broker (thiết bị A không giả mạo/nghe lén B), tin MQTT hỏng, phản hồi giả | Bảo mật |
| `test_07_mvp_chua_xong.py` | TC-70..77 | Chức năng MVP chưa có (xfail) | Theo dõi tiến độ |
| `test_08_hieu_nang.py` | TC-80..87 | Thời gian phản hồi API, độ trễ lệnh, thông lượng telemetry, tải đồng thời, bcrypt | Phi chức năng |
| `test_09_broker_that.py` | TC-90..95 | Lặp lại kiểm tra ACL + đo độ trễ trên Mosquitto thật | Bảo mật + phi chức năng |

## Test xfail (chưa đạt, đã biết)

`xfail` = test viết sẵn cho hành vi cần có, hiện chưa đạt nên không làm đỏ cả bộ.
Sửa xong mục nào thì **xóa dòng `@pytest.mark.xfail`** của test đó.

| Test | Việc cần làm |
| --- | --- |
| TC-70, TC-71 | Sinh cảnh báo khi telemetry vượt `alert_rules` và khi thiết bị mất kết nối |
| TC-72, TC-73 | Quạt tự bật theo nhiệt độ; cảm biến lỗi thì bật quạt (fail-safe) |
| TC-74 | Lệnh `feed` (mở máng → chờ → đóng) |
| TC-75 | `POST /barns/{id}/commands` mà frontend đang gọi |
| TC-76 | Tắt `sequence.autostart` của servo trong `firmware/config.example.json` |
| TC-77 | ESP32 dùng MQTT TLS (8883) như báo cáo |
| TC-66 | `GET /devices/...` phải kiểm quyền theo chuồng (hiện Operator chuồng 2 xem được chuồng 1) |
| TC-87 | Hơn 15 lệnh cùng lúc làm nghẽn pool kết nối DB (mỗi request giữ 1 kết nối trong lúc chờ ESP32) |

Tên lệnh/đường dẫn trong TC-72..75 là dự kiến; nếu nhóm đặt tên khác thì sửa test cho khớp.
