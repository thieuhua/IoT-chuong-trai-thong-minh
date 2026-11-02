# Backend IoT

Chạy các lệnh sau tại thư mục `backend/` với Python 3.11. Broker trong
`deployment/` cần đang chạy; backend đọc mật khẩu từ `../deployment/.env`.

```powershell
..\.venv\Scripts\python.exe -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

API tương tác: <http://localhost:8000/docs>. `GET /events` cung cấp SSE cho
telemetry, trạng thái, đăng ký và cập nhật thiết bị. API không trả mật khẩu
hoặc hash của đăng ký. Đổi file cấu hình bằng biến `IOT_ENV_FILE`;
`IOT_DB_PATH` mặc định là `data/iot.sqlite3` (tính từ thư mục chạy lệnh).

Chạy ba thiết bị giả lập trong terminal khác:

```powershell
.venv\Scripts\python.exe tools/sim_device.py --count 3 --env ../deployment/.env
```

Simulator lưu định danh/mật khẩu trong `data/sim/`, gửi yêu cầu mỗi 10 giây.
Dùng `GET /registrations`, sau đó `POST /registrations/{hw_id}/approve` với
body `{}` để duyệt. Mặc định cần duyệt thủ công; `IOT_AUTO_APPROVE=1` chỉ dành
cho phát triển. `IOT_AUTH_MODE=none` dùng với broker anonymous.

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pytest -q -m "not integration"
```

Integration tự bỏ qua khi thiếu `deployment/.env` hoặc không kết nối được
`127.0.0.1:1883`. Test dùng DB/thư mục tạm, định danh `7e57…` và dọn tài khoản,
role, retained status/meta sau khi chạy; không khởi động lại broker.

## Dùng iot_core trong server thật

`iot_core` độc lập FastAPI. Có thể thay registry, telemetry store hoặc broker
auth qua constructor; các callback nhận hàm thường hoặc coroutine, trả về hàm hủy đăng ký.

```python
import asyncio
from iot_core import DeviceGateway, GatewayConfig

async def main():
    config = GatewayConfig.from_env("../deployment/.env")
    async with DeviceGateway.from_config(config) as gateway:
        unsubscribe = gateway.on_telemetry(lambda record: print(record.readings))
        for request in await gateway.list_registrations():
            print("Cần duyệt:", request.hw_id)
        for device in await gateway.list_devices(online=True):
            print(device.name, await gateway.read_all(device.device_id))
            await gateway.set_interval(device.device_id, 10)
        unsubscribe()

asyncio.run(main())
```

DynSec Mosquitto 2.0.22 đã kiểm tra: `Role already exists`,
`ACL with this topic already exists`, `Client already exists`, `Client not found`,
`Role not found`. Thêm lại role đang có trả `Internal error`; backend kiểm tra
membership và gỡ membership đó trước khi thêm lại, không bỏ qua lỗi bất ngờ.
