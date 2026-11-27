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
   `wifi` là danh sách theo thứ tự ưu tiên; object cũ vẫn dùng được. Ví dụ:
   `"wifi": [{"ssid":"Hotspot laptop","password":"...","mqtt_host":"192.168.137.1"}, {"ssid":"Wifi nha","password":"..."}]`.
   `mqtt_host`/`mqtt_port` của từng mạng ghi đè `mqtt.host`/`mqtt.port`; bỏ qua để dùng mặc định.
   Board thử các mạng đang thấy theo ưu tiên; quét lỗi/không thấy mạng đã cấu hình thì thử tất cả.
   Kết nối đang hoạt động được giữ nguyên; serial và `get_info.ssid` cho biết mạng đang dùng.
   DHT11 dùng GPIO25 (G34–39 chỉ đọc vào, không dùng được); servo SG90 ở G14 cần nguồn 5 V ≥ 2 A; relay ở G26.
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

## Script tiện ích

Chạy từ gốc repo. Script PowerShell dùng `.venv/Scripts/mpremote.exe` hoặc
`.venv/Scripts/esptool.exe`; báo lỗi nếu thiếu. Python chỉ dùng thư viện chuẩn.

| Script | Dùng khi nào | Ví dụ một dòng |
| --- | --- | --- |
| `firmware/tools/board.ps1` | `ports`, `monitor`, `info`, `scan`, `backup`, `reset` qua USB | `powershell -File firmware/tools/board.ps1 info -Port COM3` |
| `firmware/tools/flash_micropython.ps1` | Xóa board và nạp binary mới nhất trong `firmware/bin/` (tự tải MicroPython 1.29.0 kèm kiểm tra SHA-256 nếu chưa có), hoặc chọn `-Bin`; gõ `yes` để xác nhận (`-Force` bỏ câu hỏi) | `powershell -File firmware/tools/flash_micropython.ps1 -Port COM3 -WhatIf` |
| `firmware/tools/make_config.py` | `init` từ example và mật khẩu bootstrap trong `deployment/.env`; `wifi-add`, `wifi-remove`, `wifi-list`, `check` | `python firmware/tools/make_config.py wifi-add "Wifi nha" --mqtt-host 192.168.1.20 --first` |
| `backend/tools/device_cmd.py` | Đăng nhập REST, liệt kê thiết bị hoặc gửi lệnh; mật khẩu nhập ẩn | `python backend/tools/device_cmd.py --user admin esp32-ID ping` |

`make_config.py init` giữ file đã có, chỉ ghi đè với `--force`. `wifi-add` cập nhật nếu
trùng SSID, nhập mật khẩu bằng prompt hoặc `--password-stdin`; `wifi-list` không in mật khẩu.
`check` cảnh báo trường còn `YOUR_...`/`FROM_...`. Dùng `--help` để xem thêm ví dụ lệnh REST.
`board.ps1 backup` lưu các JSON có trên board vào `firmware/bin/board_backups/<yyyyMMdd_HHmmss>/`
(đã được Git bỏ qua qua quy tắc `bin/`); bản backup có mật khẩu, cần giữ riêng.
`mpremote exec` tự ngắt app bằng Ctrl+C; WDT vẫn chạy nếu `watchdog_s > 0`.
Trong monitor, Ctrl+] để thoát. Sau flash, chạy `deploy.ps1 -Config` rồi duyệt đăng ký lại.

Host tests (không truy cập board): `.venv/Scripts/python.exe -m pytest firmware/tests -q`.
Nếu venv repo chưa có pytest, tạo `firmware/.venv` từ Python repo rồi chỉ cài pytest
trong đó; chạy `firmware/.venv/Scripts/python.exe -m pytest firmware/tests -q`.
