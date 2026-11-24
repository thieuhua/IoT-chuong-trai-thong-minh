# Hệ thống giám sát và điều khiển chuồng trại thông minh (IoT)

Bài tập lớn môn IoT và ứng dụng, Nhóm 19 (Học viện Công nghệ Bưu chính Viễn thông), giảng viên Kim Ngọc Bách.

Mỗi chuồng có một ESP32 chạy MicroPython đọc DHT11, bật tắt quạt 5 V và mở máng ăn bằng servo SG90. Thiết bị nói chuyện với backend FastAPI + MySQL qua MQTT (Mosquitto, Dynamic Security, mỗi thiết bị một tài khoản). Web React hiển thị dashboard, biểu đồ, cảnh báo và điều khiển theo 3 vai trò Admin, Operator, Viewer.

| Thành viên | MSSV | GitHub |
| --- | --- | --- |
| Hứa Xuân Thiệu (nhóm trưởng) | B23DCCN788 | thieuhua |
| Hoàng Anh Minh | B23DCCN544 | HoangAnhMinhCN |
| Bùi Hồng Phong | B23DCCN641 | Pp |

- Báo cáo: [docs/bao-cao/](docs/bao-cao/) (docx + PDF)
- Giao thức MQTT: [docs/protocol.md](docs/protocol.md)
- Phần cứng, sơ đồ chân, BOM: [hardware/](hardware/)
- CSDL: [database/schema.sql](database/schema.sql)
- Biến môi trường mẫu: [.env.example](.env.example) (bản dùng thật đặt ở `deployment/.env`)
- Kiểm thử hệ thống: [tests/](tests/)

## Nền tảng thiết bị ESP32 + Mosquitto

| Thư mục | Nội dung |
| --- | --- |
| [docs/protocol.md](docs/protocol.md) | Giao thức MQTT v1: topic, envelope, đăng ký thiết bị, lệnh, quyền broker |
| [docs/remote-dev.md](docs/remote-dev.md) | Làm việc từ xa: chạy backend riêng qua `mqtt.xuanthieu.site`, điều khiển và OTA ESP32 |
| [deployment/](deployment/compose.yaml) | Mosquitto 2.0.22 (Docker) với Dynamic Security, mỗi thiết bị một tài khoản |
| [backend/](backend/README.md) | `iot_core` (`DeviceGateway`), server tạm FastAPI, simulator, test |
| [firmware/](firmware/README.md) | Firmware MicroPython chia module, `tools/deploy.ps1` |

## Chạy nhanh bằng Docker

Chạy các lệnh dưới đây bằng PowerShell tại thư mục gốc repo, trừ khi có ghi chú.

1. Cài và mở Docker Desktop. Chép [deployment/.env.example](deployment/.env.example)
   thành `deployment/.env` nếu chưa có; cấu hình mật khẩu broker, bỏ dấu `#` và điền
   `DATABASE_URL`, `JWT_SECRET_KEY` bằng giá trị riêng.
   MySQL phải chạy trên máy ở cổng **3306**, có sẵn database theo `DATABASE_URL`.
   Trên Windows, mở **PowerShell Administrator** và chạy `Start-Service MySQL8044`.
   Backend trong Docker tự đổi host `localhost`/`127.0.0.1` trong URL MySQL thành
   `host.docker.internal`.
2. Nếu chưa có `just`, cài bằng `winget install --id Casey.Just -e`.
   Các lệnh sau dùng profile `app` trong [deployment/compose.yaml](deployment/compose.yaml):

   | Lệnh `just` | Tương đương khi không có `just` |
   | --- | --- |
   | `just up` | `docker compose -f deployment/compose.yaml --profile app up -d --build --wait` |
   | `just down` | `docker compose -f deployment/compose.yaml --profile app down` |
   | `just status` | `docker compose -f deployment/compose.yaml --profile app ps` |
   | `just logs [service]` | `docker compose -f deployment/compose.yaml --profile app logs --tail 100 -f [service]` |

   `[service]` là tùy chọn: bỏ đi để xem tất cả, hoặc thay bằng `backend`, `frontend`,
   `mosquitto` (ví dụ `just logs backend`). Nhấn Ctrl+C để ngừng xem log.
3. Sau khi `just up` thành công, tạo tài khoản `admin` bằng môi trường Python backend
   đã cài dependency trên máy:

   ```powershell
   cd backend
   .venv\Scripts\python.exe -m app.create_admin
   cd ..
   ```

   Mật khẩu mặc định xem trong [backend/app/create_admin.py](backend/app/create_admin.py);
   đổi mật khẩu ngay sau khi đăng nhập.

Web: <http://localhost:8080>; API: <http://localhost:8000/docs>; broker MQTT: cổng **1883**
(cổng mặc định). Image backend không hỗ trợ camera. Không chạy `just backend` cùng lúc
với backend Docker vì trùng cổng **8000**.

**Demo servo/relay từ điện thoại:** bật hotspot laptop, kết nối điện thoại và ESP32
vào hotspot, bảo đảm thiết bị đã được duyệt và online. Thay `esp32-<hw_id>` bằng ID thật:

```powershell
.\backend\.venv\Scripts\python.exe -B .\demo\servo_slider\server.py --device esp32-<hw_id> --bind 192.168.137.1 --port 8081
```

Trên điện thoại mở <http://192.168.137.1:8081> (đổi IP bind và URL nếu hotspot dùng IP khác).
Trang có quyền **Admin**, ai truy cập được cũng điều khiển được thiết bị; **chỉ dùng hotspot riêng**.
Chi tiết: [demo/servo_slider/README.md](demo/servo_slider/README.md).

### Chạy backend trực tiếp

Chạy nhanh (PowerShell, tại thư mục gốc; dùng thay cho profile `app`):

```powershell
# Chỉ chép khi chưa có .env (chép đè sẽ mất mật khẩu thật), rồi đổi hai mật khẩu
if (-not (Test-Path deployment\.env)) { Copy-Item deployment\.env.example deployment\.env }
docker compose -f deployment\compose.yaml up -d --wait
Set-Location backend; .venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Firmware: chép `firmware/config.example.json` thành `firmware/src/config.json` (Wi-Fi, IP hotspot,
mật khẩu bootstrap trong `deployment/.env`), rồi `powershell -File firmware\tools\deploy.ps1 -Config`.
Board in `hw_id` trên serial và chờ duyệt; duyệt tại <http://localhost:8000/docs>
(`POST /registrations/{hw_id}/approve`).

Hotspot laptop có thể không có Internet: khi đó NTP lỗi, thiết bị gửi `ts: null` và server dùng giờ nhận.
Nếu COM3 báo "A device attached to the system is not functioning", rút/cắm lại USB, dùng cáp/cổng tốt hơn
(Wi-Fi của ESP32 hút dòng mạnh, cáp yếu làm chip USB-UART chập chờn).

## MQTT qua TLS và Laptop Tunnel

`deployment/compose.yaml` chạy broker LAN như trong phần chạy nhanh. Backend mặc định
kết nối `127.0.0.1:1883` theo `deployment/.env.example`. Máy có Laptop Tunnel có thể
chọn thêm `deployment/compose.tunnel.yaml`. Cấu hình này publish TLS trên IP WireGuard
và cổng được VPS chuyển tiếp, đồng thời giữ MQTT plaintext ở `127.0.0.1:1883`.
ESP32 ở hotspot laptop tiếp tục dùng MQTT trực tiếp tại `IOT_LAN_BIND_IP:1883`.

Trên máy có tunnel, đặt các biến sau trong `deployment/tunnel.local.ps1` (Git bỏ qua).
Thay IP, cổng và tên miền bằng thông số của tunnel. `IOT_ENV_FILE` có thể trỏ tới
đường dẫn tuyệt đối của `.env` ở checkout đang cung cấp cấu hình broker.

```powershell
$env:IOT_LAN_BIND_IP = '192.168.137.1'
$env:IOT_TUNNEL_BIND_IP = '10.0.0.2'
$env:IOT_TUNNEL_PORT = '20001'
$env:IOT_BROKER_HOST = 'mqtt.example.com'
$env:IOT_BROKER_PORT = $env:IOT_TUNNEL_PORT
$env:IOT_BROKER_TLS = '1'
```

Tạo bản ghi DNS only cho hostname MQTT trỏ về VPS. Cấp chứng chỉ bằng DNS-01 nếu
Docker volume `iot-mqtt-tls` chưa có chứng chỉ. Làm theo yêu cầu TXT của Certbot trước
khi chạy Compose.

```powershell
. ./deployment/tunnel.local.ps1
$hook = 'install -m 644 $RENEWED_LINEAGE/fullchain.pem /tls/fullchain.pem && install -o 1883 -g 1883 -m 640 $RENEWED_LINEAGE/privkey.pem /tls/privkey.pem'
docker run --rm -it -v iot-mqtt-acme:/etc/letsencrypt -v iot-mqtt-tls:/tls certbot/certbot certonly --manual --preferred-challenges dns --key-type rsa --preferred-chain 'ISRG Root X1' --cert-name $env:IOT_BROKER_HOST -d $env:IOT_BROKER_HOST --deploy-hook $hook
docker compose -f deployment/compose.yaml -f deployment/compose.tunnel.yaml up -d --wait
```

Để backend dùng địa chỉ công cộng, khởi động backend từ terminal đã nạp
`tunnel.local.ps1`. Để tắt listener tunnel, chạy lại Compose chỉ với
`deployment/compose.yaml`. Gia hạn thủ công bằng
lệnh Certbot trên trước khi chứng chỉ hết hạn, sau đó chạy lại Compose với
`up -d --force-recreate --wait` để Mosquitto nạp chứng chỉ mới.

## Demo MQTT

Mã nguồn và hướng dẫn chạy demo cũ (broker anonymous) nằm trong [demo/README.md](demo/README.md).
Demo và nền tảng mới cùng dùng cổng 1883: chỉ chạy một broker tại một thời điểm.
