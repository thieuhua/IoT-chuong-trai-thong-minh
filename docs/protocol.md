# Giao thức MQTT thiết bị — v1

Tài liệu này là hợp đồng duy nhất giữa firmware ESP32 (`firmware/`) và backend (`backend/iot_core`). Mọi thay đổi topic hay payload phải sửa ở đây trước, rồi sửa `firmware/src/core/protocol.py` và `backend/iot_core/protocol.py` cho khớp.

## 1. Định danh

| Tên | Ý nghĩa | Ví dụ |
| --- | --- | --- |
| `hw_id` | Mã phần cứng, hex chữ thường của `machine.unique_id()` (6 byte trên ESP32). Không bí mật, chỉ dùng để nhận diện yêu cầu đăng ký. | `a0b1c2d3e4f5` |
| `device_id` | Mã thiết bị do backend cấp khi duyệt. Mặc định `esp32-<hw_id>`. Đồng thời là MQTT username và client id. | `esp32-a0b1c2d3e4f5` |
| `name` | Tên hiển thị do admin đặt, chỉ backend lưu. | `Phòng khách` |

`device_id` chỉ gồm `[a-z0-9-]`, dài 3–48 ký tự. Giá trị `provision` bị cấm vì trùng nhánh topic đăng ký.

## 2. Vỏ thông điệp (envelope)

Mọi payload là JSON UTF-8, tối đa 4096 byte:

```json
{"v": 1, "id": "3-17", "ts": 1793577600, "type": "telemetry", "data": {}}
```

| Trường | Kiểu | Ghi chú |
| --- | --- | --- |
| `v` | int | Phiên bản giao thức. Bên nhận bỏ qua (và ghi log) thông điệp có `v` không hỗ trợ. |
| `id` | string | Duy nhất trong phạm vi người gửi. ESP32 dùng `"<boot>-<seq>"` (bộ đếm khởi động lưu flash + số thứ tự). Backend dùng uuid4 hex. |
| `ts` | int \| null | Giây Unix UTC lúc gửi, **số nguyên** (float 32-bit của ESP32 sai tới ~128 s ở giá trị epoch hiện nay). ESP32 gửi `null` khi chưa đồng bộ NTP. Backend luôn lưu thêm `received_at` của riêng mình và coi `ts` của thiết bị chỉ là tham khảo. |
| `type` | string | Xem từng topic bên dưới. |
| `data` | object | Nội dung theo `type`. |

## 3. Bảng topic

Tiền tố chung `iot/v1`. `{id}` là `device_id`, `{hw}` là `hw_id`.

| Topic | Chiều | QoS | Retain | `type` |
| --- | --- | --- | --- | --- |
| `iot/v1/provision/{hw}/request` | thiết bị → backend | 0 | không | `provision.request` |
| `iot/v1/provision/{hw}/response` | backend → thiết bị | 1 | **không** | `provision.response` |
| `iot/v1/{id}/status` | thiết bị → backend | 1 | **có** | `status` |
| `iot/v1/{id}/meta` | thiết bị → backend | 1 | **có** | `meta` |
| `iot/v1/{id}/telemetry` | thiết bị → backend | 0 | không | `telemetry` |
| `iot/v1/{id}/cmd` | backend → thiết bị | 1 | không | `cmd` |
| `iot/v1/{id}/resp` | thiết bị → backend | 0 | không | `resp` |

Backend đăng ký: `iot/v1/provision/+/request`, `iot/v1/+/status`, `iot/v1/+/meta`, `iot/v1/+/telemetry`, `iot/v1/+/resp`.
Thiết bị đã đăng ký chỉ subscribe `iot/v1/{id}/cmd`. Thiết bị chưa đăng ký chỉ subscribe `iot/v1/provision/{hw}/response`.

## 4. Đăng ký thiết bị mới (provisioning)

```text
ESP32 (chưa có /device.json)                 Backend
  | connect user=bootstrap, client_id={hw}      |
  | sub  provision/{hw}/response                |
  | pub  provision/{hw}/request  ─────────────▶ | lưu đăng ký "pending" (hoặc tự duyệt)
  | ◀───────────── provision/{hw}/response      | status=pending
  |   ... gửi lại request mỗi 10 s ...          |
  |                                             | admin gọi approve(hw_id)
  |                                             | tạo MQTT client {id} với mật khẩu thiết bị đã gửi
  | ◀───────────── provision/{hw}/response      | status=approved, device_id={id}
  | ghi /device.json, ngắt kết nối               |
  | connect user={id}, client_id={id}           |
  | pub status(online), meta  ────────────────▶ | thiết bị "online"
```

`provision.request` — `data`:

```json
{
  "hw_id": "a0b1c2d3e4f5",
  "model": "esp32",
  "fw": "0.1.0",
  "password": "9f2c…(32 hex do thiết bị tự sinh bằng os.urandom, lưu flash)",
  "sensors": [{"name": "room", "driver": "dht11", "fields": {"temperature": "°C", "humidity": "%"}}],
  "commands": ["ping", "get_info", "read", "set_interval", "reboot"]
}
```

`provision.response` — `data`:

```json
{"status": "pending" | "approved" | "rejected", "device_id": "esp32-a0b1c2d3e4f5", "reason": "…"}
```

`device_id` chỉ có khi `approved`, `reason` chỉ có khi `rejected`.

Quy tắc:

- Mật khẩu do **thiết bị** sinh, backend không bao giờ gửi mật khẩu đi. Thiết bị giữ nguyên mật khẩu này qua các lần gửi lại.
- Backend trả lời idempotent: cùng `hw_id` gửi lại nhiều lần thì cùng kết quả.
- `hw_id` đã được duyệt mà gửi request mới (ví dụ flash bị xóa): backend đưa về `pending` và cần admin duyệt lại, không tự cấp lại quyền (trừ khi bật `AUTO_APPROVE`).
- Khi đăng nhập bằng tài khoản thiết bị bị từ chối (CONNACK `not authorised`, ví dụ đã bị thu hồi), thiết bị xóa `/device.json` và quay lại bước đăng ký.

## 5. Trạng thái và khả năng

`status` — `data`: `{"state": "online" | "offline", "reason": "lwt" | "reboot" | "shutdown"}`.

- Thiết bị đặt Last Will `{"state": "offline", "reason": "lwt"}` (retained) trước khi `connect()`.
- Ngay sau khi kết nối: subscribe `cmd` **trước**, rồi mới publish `online` (retained) và `meta` (retained). Backend có thể gửi lệnh ngay khi thấy `online`; với clean session, lệnh tới trước SUBSCRIBE sẽ mất.
- Trước khi chủ động reboot/ngắt: publish `offline` với lý do tương ứng, vì Last Will không chạy khi ngắt kết nối sạch.
- Khi thu hồi thiết bị, backend publish payload rỗng retained vào `status` và `meta` để xóa thông điệp giữ lại.

`meta` — `data`:

```json
{
  "hw_id": "a0b1c2d3e4f5", "model": "esp32", "fw": "0.1.0",
  "sensors": [{"name": "room", "driver": "dht11", "fields": {"temperature": "°C", "humidity": "%"}}],
  "commands": ["ping", "get_info", "read", "set_interval", "reboot"],
  "interval_s": 10,
  "actuators": [{"name": "servo", "driver": "servo", "pin": 26, "range": [0, 180]}]
}
```

`actuators` chỉ có khi thiết bị khai báo cơ cấu chấp hành (servo, relay...). Backend hiện lưu nguyên `meta`
nhưng chưa có trường riêng cho actuator; trạng thái đọc qua lệnh `get_info` hoặc kết quả lệnh điều khiển.

## 6. Telemetry

`telemetry` — `data`:

```json
{
  "readings": {"room": {"temperature": 24, "humidity": 61}},
  "errors": {"soil": "timeout"}
}
```

`readings` gom theo tên cảm biến, mỗi cảm biến trả về các trường (`fields`) đã khai báo trong `meta`. `errors` chỉ có khi có cảm biến đọc lỗi. Chu kỳ gửi là `interval_s`.

## 7. Lệnh và phản hồi

`cmd` — `data`: `{"name": "read", "args": {"sensor": "room"}, "ttl_s": 30}`.
Envelope `id` của lệnh dùng làm mã ghép phản hồi. Thiết bị bỏ qua lệnh đã quá hạn nếu đã có giờ NTP (`ts + ttl_s < now`). Lệnh không được xếp hàng khi thiết bị offline: backend coi lệnh là "best effort", hết thời gian chờ thì báo lỗi `timeout`.

`resp` — `data`:

```json
{"re": "<id của lệnh>", "ok": true, "result": {}}
{"re": "<id của lệnh>", "ok": false, "error": {"code": "sensor_not_found", "message": "no sensor 'x'"}}
```

| Lệnh | `args` | `result` |
| --- | --- | --- |
| `ping` | — | `{"uptime_s": 123}` |
| `get_info` | — | nội dung `meta` + `{"uptime_s", "mem_free", "rssi", "ip"}` |
| `read` | `{"sensor": "room"}` hoặc `{}` (tất cả) | giống `data` của telemetry |
| `set_interval` | `{"seconds": 10}` (1–3600) | `{"interval_s": 10}`; thiết bị lưu vào flash |
| `reboot` | — | `{}`; thiết bị trả lời, publish `offline` (`reboot`), rồi reset sau ~1 s |
| `servo_set` | `{"name": "servo", "angle": 90}` (0–180; `name` bỏ được khi chỉ có 1 actuator) | trạng thái servo; dừng chuỗi góc nếu đang chạy |
| `servo_sequence` | `{"name": "servo", "run": true, "angles": [0, 20, …, 180], "step_ms": 1000}` (`angles`, `step_ms` tùy chọn; `run: false` để dừng) | trạng thái servo |

Trạng thái servo: `{"angle": 40, "running": true, "angles": [0, 20, …, 180], "step_ms": 1000}`.
Chuỗi góc chạy bằng hardware timer trên thiết bị (không phụ thuộc kết nối mạng) và lặp vô hạn; cấu hình
khởi động nằm trong `config.json` (`sequence.autostart`). Thay đổi bằng lệnh không lưu qua lần khởi động lại.

Mã lỗi: `unknown_command`, `bad_args`, `sensor_not_found`, `sensor_error`, `actuator_not_found`, `internal`.
Thêm lệnh mới: khai báo ở bảng này, đăng ký handler trong `firmware/src/commands.py`, thêm hàm tiện ích trong `DeviceGateway` nếu cần.

## 8. Quyền trên broker (Mosquitto Dynamic Security)

Mặc định từ chối publish và subscribe, cho phép nhận. Các role:

| Role | Client | ACL |
| --- | --- | --- |
| `admin` + `backend` | `backend` (admin dynsec, tạo lúc khởi tạo broker) | subscribe `#`; publish `iot/v1/#` và `$CONTROL/dynamic-security/#` |
| `bootstrap` | `bootstrap` (mật khẩu dùng chung, nạp trong `config.json` của firmware) | publish `iot/v1/provision/+/request`; subscribe `iot/v1/provision/+/response` |
| `dev-{id}` | `{id}`, mỗi thiết bị một client, `username = client_id = device_id` | publish `iot/v1/{id}/status`, `/meta`, `/telemetry`, `/resp`; subscribe `iot/v1/{id}/cmd` |

Mosquitto 2.0 **không** thay `%c`/`%u` trong ACL của Dynamic Security (đã kiểm tra với 2.0.22), nên backend tạo role `dev-{id}` với topic ghi rõ khi duyệt, và xóa role đó khi thu hồi. Client thiết bị được ghim `clientid = device_id`, kết nối bằng client id khác bị từ chối.

`bootstrap` không subscribe được `provision/+/request`, nên không đọc được mật khẩu thiết bị khác gửi lên. `response` không chứa bí mật nên cho phép đọc chung.

Thay đổi role/client bằng dynsec sẽ ngắt kết nối client bị ảnh hưởng; backend chỉ sửa client thiết bị, không sửa chính nó lúc chạy.

Chế độ `AUTH_MODE=none` (giống demo cũ) bỏ toàn bộ phần này: broker cho anonymous, backend duyệt đăng ký nhưng không tạo tài khoản.

## 9. Giới hạn đã biết

- Không có TLS: ai nghe được mạng LAN đều thấy mật khẩu và dữ liệu. Chỉ dùng trên LAN phát triển tin cậy.
- `hw_id` là địa chỉ MAC, có thể bị giả mạo. Vì vậy mặc định cần admin duyệt; `AUTO_APPROVE` chỉ dành cho phát triển.
- Tài khoản `bootstrap` dùng chung: lộ mật khẩu này chỉ cho phép gửi yêu cầu đăng ký và đọc trạng thái duyệt, không đọc được mật khẩu hay dữ liệu thiết bị khác. Thiết bị bootstrap có thể gửi request mang `hw_id` của máy khác; vì vậy admin duyệt theo `hw_id` in ra trên serial của board.
- ESP32 dùng `umqtt.simple` với clean session: lệnh gửi khi thiết bị offline sẽ mất.
