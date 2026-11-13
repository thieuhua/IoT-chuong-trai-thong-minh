# Firmware ESP32 / MicroPython 1.29

Firmware dùng `network.WLAN`, `umqtt.simple` và giao thức trong `docs/protocol.md`.
Không cần `boot.py`. Trên board: `/main.py` là bộ khởi động cố định (`src/main.py`), code
ứng dụng (mọi file khác trong `src/`) nằm trong `/app/`, dữ liệu ở thư mục gốc.

## Nạp code

**Lần đầu (hoặc cứu board) qua USB**, từ thư mục repo:
`powershell -File firmware/tools/deploy.ps1 -Port COM3 -Config`.
`-Config` chép cả `src/config.json`; `-Wipe` xóa `/device.json` và `/state.json` (phải duyệt
đăng ký lại). Script xóa trạng thái OTA cũ, không cài hay flash MicroPython. Khi cắm USB vào
laptop, rút dây 5V của servo (nguồn USB không đủ, board sẽ brownout).

**Các lần sau qua Wi-Fi** (board cắm củ sạc, server tạm đang chạy):
`cd backend; .venv\Scripts\python.exe tools\ota_push.py --device esp32-<hw_id>`.
Chỉ file thay đổi được gửi; board khởi động lại, chạy bản mới ở chế độ thử và tự xác nhận sau
khi online 30 s và trả lời được một lệnh. Bản mới crash/treo/không kết nối được thì sau 2 lần
khởi động board tự quay về bản cũ (`ota_status.rolled_back_from`). `--with-config` gửi kèm
`src/config.json`; sai Wi-Fi/broker cũng được rollback. `src/main.py` chỉ cập nhật được qua USB.

## Cấu hình và đăng ký

1. Chép `config.example.json` thành `src/config.json`; nhập Wi-Fi, MQTT host và
   mật khẩu bootstrap được quản trị viên cung cấp. Không commit file cấu hình thật.
   DHT11 dùng GPIO14 (G34–39 chỉ đọc vào, không dùng được); servo SG90 ở G26 cần nguồn 5 V ≥ 2 A.
2. Nạp lần đầu qua USB như trên.
3. Lần khởi động đầu, xem `hw_id` trên serial và chờ quản trị viên duyệt đăng ký.
   Firmware lưu mật khẩu ngẫu nhiên một lần trong `/device.json`; khi được duyệt,
   chuyển sang tài khoản riêng, gửi online/meta và telemetry mỗi `interval_s`.
   Thu hồi tài khoản làm firmware xóa thông tin đăng ký và đăng ký lại.

`/state.json` lưu số lần boot và chu kỳ từ `set_interval` (ưu tiên hơn config).
Không có NTP thì `ts=null`; chỉ bỏ lệnh quá TTL khi đã đồng bộ giờ.
Ctrl+C dừng chương trình và trả về REPL để mpremote thao tác.

Thêm sensor: kế thừa `sensors.base.Sensor`, khai báo `driver`, `fields`,
`min_interval_ms` và `_measure()` trả dict; thêm lớp vào bảng `sensors.DRIVERS`
và cấu hình với `name` duy nhất. Driver được import khi dùng. Các driver có sẵn:
`dht11`, `dht22`, `adc` (pin 34, atten `11db`, raw 0..65535, voltage V), `simulated`.
Đọc trước khi DHT ổn định trong 2 giây đầu sẽ báo lỗi tạm thời; đọc liên tiếp dùng cache.

Thêm lệnh: viết hàm `handler(ctx, args)` trả dict trong `commands.py`, gắn
`@register("ten_lenh")`; lỗi dùng `CommandError`. Cập nhật bảng lệnh trong giao thức
và backend khi cần. `read` tất cả giữ lỗi theo tên trong `errors`; đọc riêng sensor lỗi
trả `sensor_error`, tên không tồn tại trả `sensor_not_found`.

Giữ `watchdog_s: 0` khi phát triển: WDT đã bật không thể dừng, kể cả khi Ctrl+C.
Khi bật, đặt timeout đủ lớn cho thao tác mạng đồng bộ (DNS/connect/QoS1 có thể chặn).
Các vòng Wi-Fi, provisioning, session và chờ backoff đều feed WDT.

Host tests (không truy cập board): `.venv/Scripts/python.exe -m pytest firmware/tests -q`.
Nếu venv repo chưa có pytest, tạo `firmware/.venv` từ Python repo rồi chỉ cài pytest
trong đó; chạy `firmware/.venv/Scripts/python.exe -m pytest firmware/tests -q`.
