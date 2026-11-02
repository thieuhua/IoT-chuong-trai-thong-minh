# Firmware ESP32 / MicroPython 1.29

Firmware dùng `network.WLAN`, `umqtt.simple` và giao thức trong `docs/protocol.md`.
Không cần `boot.py`. Toàn bộ nội dung `src/` được chép vào thư mục gốc board.

1. Chép `config.example.json` thành `src/config.json`; nhập Wi-Fi, MQTT host và
   mật khẩu bootstrap được quản trị viên cung cấp. Không commit file cấu hình thật.
   DHT11 dùng GPIO23, chân DATA kéo lên; có thể chỉ giữ sensor `simulated` để thử không cần dây.
2. Khi có board, từ thư mục repo chạy:
   `powershell -File firmware/tools/deploy.ps1 -Port COM3 -Config`.
   Các lần sau bỏ `-Config` để giữ cấu hình trên board. `-Wipe` xóa cả `/device.json`
   và `/state.json`, cần duyệt đăng ký lại. Script không cài hay flash MicroPython.
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
