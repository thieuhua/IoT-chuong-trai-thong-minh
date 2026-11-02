


```
py -3.11 venv .venv


```

## Nền tảng thiết bị ESP32 + Mosquitto

| Thư mục | Nội dung |
| --- | --- |
| [docs/protocol.md](docs/protocol.md) | Giao thức MQTT v1: topic, envelope, đăng ký thiết bị, lệnh, quyền broker |
| [deployment/](deployment/compose.yaml) | Mosquitto 2.0.22 (Docker) với Dynamic Security, mỗi thiết bị một tài khoản |
| [backend/](backend/README.md) | `iot_core` (`DeviceGateway`), server tạm FastAPI, simulator, test |
| [firmware/](firmware/README.md) | Firmware MicroPython chia module, `tools/deploy.ps1` |

Chạy nhanh (PowerShell, tại thư mục gốc):

```powershell
Copy-Item deployment\.env.example deployment\.env   # rồi đổi hai mật khẩu
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

## Demo MQTT

Mã nguồn và hướng dẫn chạy demo cũ (broker anonymous) nằm trong [demo/README.md](demo/README.md).
Demo và nền tảng mới cùng dùng cổng 1883: chỉ chạy một broker tại một thời điểm.
