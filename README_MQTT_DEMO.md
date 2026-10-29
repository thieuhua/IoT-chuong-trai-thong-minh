# MQTT MVP trên Windows: Mosquitto + Python + ESP32 tùy chọn

Chạy từ `E:\thieuh\FolderCode\IoT\Project`, trong **VS Code Windows → Terminal → New Terminal → PowerShell**. Docker Desktop phải đang chạy Linux containers. Có thể giữ dự án trên ổ E:; demo này chỉ mount một file cấu hình nhỏ nên phù hợp để bắt đầu trên Windows.

## Trạng thái đã kiểm tra trên máy này

Ngày 28/10/2026 đã chạy thành công toàn tuyến: **ESP32 → hotspot laptop → Mosquitto Docker → Python subscriber**. Broker là `192.168.137.1:1883`; ESP32 được hotspot cấp IP `192.168.137.112` (IP board có thể thay đổi). Board chạy MicroPython 1.29.0 và gửi JSON mô phỏng 5 giây/lần. Demo hiện đã được lưu vào flash, tự chạy từ `main.py` khi cấp nguồn. Đã reset cứng và nhận lại dữ liệu khi COM3 đóng, không có runner RAM hay mount từ PC. Broker hiện `healthy`, subscriber đang chạy nền. Tất cả 16 file dự án có sẵn ngoài `.git`/`.venv` đã được đối chiếu SHA-256 và giữ nguyên; môi trường `.venv` gốc không được cài thêm thư viện.

Xem dữ liệu **đang nhận** trong VS Code PowerShell:

```powershell
Set-Location 'E:\thieuh\FolderCode\IoT\Project'
Get-Content .\backend\mqtt_demo\logs\receiver.log -Tail 10 -Wait
```

`Ctrl+C` chỉ dừng xem log. Lỗi bộ nhận ở `backend/mqtt_demo/logs/receiver.err.log`. `esp32.log` và `esp32.err.log` là log của lần chạy RAM trước, không còn cập nhật. Thư mục log được Git bỏ qua. Log bộ nhận hiện ghi liên tục; khi thử xong hãy dừng demo để không tăng log vô hạn.

Ví dụ đã nhận thực tế:

```text
RX devices/esp32-mqtt-demo/data {"uptime_s": 4, "simulated": true, "sequence": 1, "device": "esp32-mqtt-demo", "temperature_c": 23.18}
```

ESP32 hiện chỉ cần nguồn USB phù hợp, có thể dùng củ sạc hoặc pin dự phòng; không cần cắm cáp dữ liệu vào PC. Laptop vẫn cần bật hotspot và Docker broker để nhận dữ liệu; Python subscriber cần chạy nếu muốn xem log. Trên board có ba file mới: `/main.py`, `/mqtt_demo_app.py` và `/mqtt_demo_settings.py`. `/boot.py` được giữ nguyên và đã sao lưu tại `firmware/mqtt_demo/board_backups/before_autostart_2026-10-28/`; trước khi nạp board chưa có `main.py`. File `firmware/src/main.py` trên PC vẫn giữ nguyên. Cấu hình riêng `firmware/mqtt_demo/mqtt_demo_settings.py` đã được tạo bằng hotspot hiện tại và được Git bỏ qua. Bản nguồn đi kèm chỉ chứa cấu hình example, không chứa mật khẩu Wi-Fi.

Để dừng bộ nhận nền và broker, dùng đoạn sau. Đoạn này kiểm tra tiến trình và đường dẫn trước khi dừng đúng bộ nhận của demo. COM3 hiện đã được giải phóng:

```powershell
Set-Location 'E:\thieuh\FolderCode\IoT\Project'
$demoRoot = (Get-Location).Path
foreach ($role in @('receiver')) {
    $pidFile = ".\backend\mqtt_demo\logs\$role.pid"
    if (Test-Path $pidFile) {
        $demoProcessId = [int](Get-Content $pidFile)
        $demoProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$demoProcessId"
        $expectedScript = "$demoRoot\backend\mqtt_demo\subscriber.py"
        if ($demoProcess -and $demoProcess.CommandLine -like "*$expectedScript*") {
            taskkill /PID $demoProcessId /T /F
        }
    }
}
docker compose -f .\deployment\mqtt_demo\compose.yaml down
```

Muốn dừng ESP32 thì ngắt nguồn board; nhấn RESET hoặc cấp nguồn lại sẽ tự chạy demo trong flash. Khi broker/hotspot tắt, board sẽ thử kết nối lại. Các bước bên dưới dùng để chạy lại backend trong terminal trực tiếp sau khi dừng bộ nhận nền; subscriber thứ hai cũng có thể chạy song song.

## File mới và luồng dữ liệu

```text
Project/
  README_MQTT_DEMO.md
  deployment/mqtt_demo/
    compose.yaml
    mosquitto.conf
  backend/mqtt_demo/
    config.py
    requirements.txt
    subscriber.py
    publisher.py
  firmware/mqtt_demo/
    .gitignore
    mqtt_demo_settings.example.py
    demo.py
    main.py
```

Python publisher / ESP32 → Mosquitto trên Docker → Python subscriber trên Windows.
Compose chỉ chạy broker; backend chạy trực tiếp bằng Python. Không cần frontend hay DB.
README, `.env`, `.gitignore`, `.venv` ở gốc và `firmware/src/main.py` có sẵn được giữ nguyên.
Các script Python không đọc `.env` có sẵn. Môi trường Python riêng của demo nằm ở `backend/mqtt_demo/.venv`, được quy tắc `.venv/` có sẵn bỏ qua trong Git.

## 1. Mở dự án và chạy broker

Trong VS Code, dùng **File → Open Folder** chọn `E:\thieuh\FolderCode\IoT\Project`.
Terminal PowerShell thứ nhất:

```powershell
Set-Location 'E:\thieuh\FolderCode\IoT\Project'
docker compose -f .\deployment\mqtt_demo\compose.yaml config
docker compose -f .\deployment\mqtt_demo\compose.yaml up -d --wait --wait-timeout 60
docker compose -f .\deployment\mqtt_demo\compose.yaml ps
docker compose -f .\deployment\mqtt_demo\compose.yaml logs --tail 30 mosquitto
```

Lần đầu cần Internet để tải image `eclipse-mosquitto:2.0.22`. `ps` phải báo `healthy` và có ánh xạ cổng 1883. Log phải có `Opening ipv4 listen socket on port 1883` và `mosquitto version ... running`. Log kết nối/publish khác là bình thường, gồm kiểm tra sức khỏe trên topic `_health/mqtt` mỗi 30 giây.

File cấu hình mount chỉ đọc; đường dẫn mount được tính từ thư mục chứa Compose. Tên Compose project riêng là `iot-mqtt-demo`; không đặt tên container cố định. Cổng 1883 phải chưa có chương trình khác chiếm dụng. Broker không tự bật lại sau khi máy khởi động lại; chạy lại lệnh `up` khi cần.

## 2. Cài thư viện Python một lần

Dự án hiện có Python 3.11 trong `.venv`. Dùng Python đó để tạo môi trường riêng, rồi cài đúng dependency của demo:

```powershell
Set-Location 'E:\thieuh\FolderCode\IoT\Project'
if (-not (Test-Path .\backend\mqtt_demo\.venv\Scripts\python.exe)) {
    & .\.venv\Scripts\python.exe -m venv .\backend\mqtt_demo\.venv
}
& .\backend\mqtt_demo\.venv\Scripts\python.exe -m pip install -r .\backend\mqtt_demo\requirements.txt
```

Không cần kích hoạt môi trường nên không cần đổi ExecutionPolicy. Trong VS Code có thể chọn **Python: Select Interpreter → Enter interpreter path** và chọn `E:\thieuh\FolderCode\IoT\Project\backend\mqtt_demo\.venv\Scripts\python.exe`.

Nếu `.venv` gốc về sau bị xóa/hỏng, dùng Python Windows 3.11+ đã cài để chạy `-m venv .\backend\mqtt_demo\.venv`; không dùng lại một môi trường Python của WSL cho các lệnh Windows.

## 3. Chạy subscriber và thông điệp tự kiểm tra

Terminal PowerShell thứ nhất:

```powershell
Set-Location 'E:\thieuh\FolderCode\IoT\Project'
& .\backend\mqtt_demo\.venv\Scripts\python.exe .\backend\mqtt_demo\subscriber.py
```

Kết quả mong đợi:

```text
READY 127.0.0.1:1883 | devices/+/data
RX devices/backend-demo/data {"device": "backend-demo", "message": "hello MQTT"}
```

Subscriber đợi broker xác nhận đăng ký rồi mới gửi thông điệp thử, nên tự nhận được thông điệp đó. Sau mỗi lần kết nối lại, subscriber đăng ký lại và gửi lại thông điệp thử. `Ctrl+C` để dừng. Dùng `--no-self-test` nếu chỉ muốn nghe dữ liệu từ publisher/ESP32.

## 4. Gửi dữ liệu từ publisher

Giữ subscriber đang chạy, mở **terminal PowerShell thứ hai**:

```powershell
Set-Location 'E:\thieuh\FolderCode\IoT\Project'
& .\backend\mqtt_demo\.venv\Scripts\python.exe .\backend\mqtt_demo\publisher.py
& .\backend\mqtt_demo\.venv\Scripts\python.exe .\backend\mqtt_demo\publisher.py --temperature 29.2
& .\backend\mqtt_demo\.venv\Scripts\python.exe .\backend\mqtt_demo\publisher.py --message 'Xin chao MQTT'
```

Mỗi lệnh gửi một lần rồi thoát. Subscriber hiện `RX devices/pc-demo/data ...`; hai lệnh đầu có JSON chứa `temperature_c`, `simulated: true`, thời gian UTC. Đây là nhiệt độ mô phỏng, không phải số đo cảm biến. Dữ liệu không dùng retain nên phải mở subscriber trước publisher.

Python publish QoS 1 và đợi broker xác nhận. QoS 1 có thể tạo bản sao thông điệp; đây chưa phải cơ chế lưu trữ hay xử lý chính xác một lần. ESP32 dùng QoS 0 để ví dụ dễ hiểu, nên có thể mất gói khi mất mạng. Broker không lưu dữ liệu ra đĩa.

Kiểm tra nhanh một lần, tự thoát sau khi nhận thông điệp thử:

```powershell
& .\backend\mqtt_demo\.venv\Scripts\python.exe .\backend\mqtt_demo\subscriber.py --once --timeout 15
```

Kiểm tra publisher riêng: chạy subscriber với `--no-self-test --once --timeout 30`, chờ `READY`, rồi chạy publisher ở terminal thứ hai trong vòng 30 giây. Các lệnh Python trả exit code 1 khi kết nối lỗi hoặc hết thời gian chờ.

## 5. Cấu hình địa chỉ và topic

| Nơi chạy client | Địa chỉ broker | Cổng |
| --- | --- | --- |
| Python chạy trên cùng máy Windows | `127.0.0.1` | `1883` |
| ESP32 / máy khác kết nối hotspot laptop | `192.168.137.1` | `1883` |
| Client chạy trong cùng mạng Compose, nếu sau này thêm | `mosquitto` | `1883` |

**ESP32 không dùng `localhost`, `127.0.0.1`, `0.0.0.0`, IP container hay IP WSL.** `localhost` trên ESP32 là chính ESP32. `0.0.0.0` chỉ là địa chỉ lắng nghe của broker.

Trong cấu hình hiện tại, ESP32 kết nối **hotspot phát từ laptop**, vì vậy chọn `Local Area Connection* 2` có IPv4 **`192.168.137.1`**; adapter hotspot không có default gateway là bình thường. Wi-Fi uplink của laptop có `10.32.243.15` nhưng ESP32 trong ví dụ dùng IP hotspot. Kiểm tra lại bằng `ipconfig` sau khi đổi mạng. Không chọn IP VMware / vEthernet / WSL.

```powershell
ipconfig
& .\backend\mqtt_demo\.venv\Scripts\python.exe .\backend\mqtt_demo\publisher.py --host 192.168.137.1 --port 1883
```

Mặc định sửa tại `backend/mqtt_demo/config.py`, hoặc truyền `--host`, `--port` cho cả hai script. Publisher nhận thêm `--topic`; topic phải khớp filter subscriber để nhận được.

| Vai trò | Topic |
| --- | --- |
| Subscriber đăng ký | `devices/+/data` (`+` khớp một cấp tên thiết bị) |
| Backend tự gửi thử | `devices/backend-demo/data` |
| PC publisher | `devices/pc-demo/data` |
| ESP32 demo mới | `devices/esp32-mqtt-demo/data` |
| Firmware cũ hiện có | `devices/esp32-01/data` — subscriber cũng nhận được |

## 6. ESP32 MicroPython tự khởi động từ flash

**Board hiện đã được nạp xong qua COM3.** Lúc cấp nguồn, MicroPython chạy `/main.py`, file này gọi chương trình `/mqtt_demo_app.py`; cấu hình được đọc từ `/mqtt_demo_settings.py`. Đã đối chiếu SHA-256 của cả ba file sau khi nạp, kiểm tra cú pháp trên board, reset cứng và nhận ba thông điệp liên tiếp khi không còn kết nối serial.

Không cần chạy `mpremote`, VS Code hoặc Python publisher trên PC để ESP32 gửi. Chỉ cần nguồn, Wi-Fi hotspot và broker. Nếu laptop khởi động lại, bật lại hotspot, Docker Desktop và Compose ở bước 1; khởi động subscriber ở bước 3 để xem dữ liệu.

Khi cần sửa mã/cấu hình và **nạp lại**, đóng ứng dụng đang giữ COM3, rồi chạy trong PowerShell ở gốc dự án:

```powershell
Set-Location 'E:\thieuh\FolderCode\IoT\Project'
& .\backend\mqtt_demo\.venv\Scripts\mpremote.exe connect COM3 soft-reset
& .\backend\mqtt_demo\.venv\Scripts\mpremote.exe connect COM3 fs cp .\firmware\mqtt_demo\demo.py :/mqtt_demo_app.py
& .\backend\mqtt_demo\.venv\Scripts\mpremote.exe connect COM3 fs cp .\firmware\mqtt_demo\mqtt_demo_settings.py :/mqtt_demo_settings.py
& .\backend\mqtt_demo\.venv\Scripts\mpremote.exe connect COM3 fs cp .\firmware\mqtt_demo\main.py :/main.py
& .\backend\mqtt_demo\.venv\Scripts\mpremote.exe connect COM3 reset
```

Các lệnh trên cập nhật đúng ba file demo trong flash. `boot.py` và thư viện MicroPython hiện có không bị thay. Mã demo tự thử lại khi lỗi mạng; nếu gặp lỗi chương trình ngoài dự kiến, `main.py` in lỗi rồi reset sau 5 giây. Nếu muốn trở về trạng thái board trước lần nạp này (chỉ có `boot.py` và không tự chạy ứng dụng), ngắt ứng dụng qua `mpremote connect COM3 soft-reset`, đổi tên `/main.py` thành `/main.mqtt-demo.disabled.py` bằng `os.rename`, rồi reset. Bản sao `boot.py` trong `board_backups` được Git bỏ qua.

### Thiết lập cấu hình hoặc thử từ RAM khi phát triển

Chỉ làm phần này khi board đã có MicroPython; không cần flash hay thay `firmware/src/main.py`. Ví dụ dùng Wi-Fi, `umqtt.simple` và tạo JSON nhiệt độ mô phỏng mỗi 5 giây. Mất kết nối sẽ thử lại; không có hàng đợi ngoại tuyến. `uptime_s` dựa trên bộ đếm MicroPython, có thể quay vòng; không phải đồng hồ UTC.

Tạo file cấu hình cá nhân nếu chưa có:

```powershell
Set-Location 'E:\thieuh\FolderCode\IoT\Project'
if (-not (Test-Path .\firmware\mqtt_demo\mqtt_demo_settings.py)) {
    Copy-Item .\firmware\mqtt_demo\mqtt_demo_settings.example.py .\firmware\mqtt_demo\mqtt_demo_settings.py
}
```

Sửa `firmware/mqtt_demo/mqtt_demo_settings.py`: tên Wi-Fi, mật khẩu và `MQTT_HOST` bằng IPv4 LAN của máy Windows. File này được `.gitignore` riêng bỏ qua; không đưa mật khẩu vào file example. ESP32 và PC cần mạng cho phép liên lạc trực tiếp; ESP32 phổ biến dùng Wi-Fi 2.4 GHz. Mạng trường/công ty hoặc guest Wi-Fi có thể chặn giao tiếp dù cùng tên Wi-Fi.

Công cụ đã được cài trong môi trường demo và board hiện ở **COM3**. Nếu muốn thử tạm một bản sửa từ RAM, đóng serial monitor khác trước:

```powershell
& .\backend\mqtt_demo\.venv\Scripts\python.exe -m pip install mpremote
& .\backend\mqtt_demo\.venv\Scripts\mpremote.exe connect list
& .\backend\mqtt_demo\.venv\Scripts\mpremote.exe connect COM3 mount .\firmware\mqtt_demo run .\firmware\mqtt_demo\demo.py
```

Board hiện đã có `umqtt.simple`, nên không cài hay thay thư viện trên board. Nếu dùng board khác thiếu thư viện, cài bằng `& .\backend\mqtt_demo\.venv\Scripts\mpremote.exe connect COM3 mip install umqtt.simple` (cần Internet trên PC; ghi thư viện vào board). Lệnh `mount ... run ...` chỉ là chế độ thử từ RAM, cần giữ cáp USB và terminal trong phiên thử. Nó ngắt chương trình đang chạy trên board, không ghi đè `main.py`. Sau reset board sẽ chạy lại demo đã lưu trong flash.

Mở Python subscriber ở terminal khác để thấy `RX devices/esp32-mqtt-demo/data ...`. Dừng thử bằng `Ctrl+C`. Đường truyền này đã kiểm tra bằng ESP32 thật ở COM3 qua hotspot `192.168.137.1`, không cần đổi firewall trên máy hiện tại.

## 7. Anonymous và truy cập LAN

`listener 1883 0.0.0.0` trong Mosquitto và ánh xạ `1883:1883` trong Compose mở broker trên các interface của máy, tùy firewall. `allow_anonymous true` cho phép client kết nối không cần tài khoản. Demo cũng không đặt ACL và không dùng TLS: **bất kỳ ai truy cập được cổng này có thể đọc/gửi dữ liệu vào các topic ứng dụng, giả mạo thiết bị hoặc gửi rác; nội dung truyền không mã hóa**.

Chỉ bật trên LAN phát triển đáng tin cậy, không forward cổng router, không dùng cho dữ liệu nhạy cảm hay mạng công cộng. Môi trường thực tế cần tài khoản, ACL và TLS. Sau khi thử hãy `down` broker. Nếu chỉ thử Python trên PC, có thể giới hạn port mapping thành `127.0.0.1:1883:1883`; khi đó ESP32 sẽ không kết nối được.

Nếu Python nhận được nhưng ESP32 không nhận: kiểm tra IP LAN, cổng, mạng 2.4 GHz, firewall và AP/client isolation. Không tắt toàn bộ Windows Firewall. Trên LAN riêng đáng tin, có thể cho phép riêng TCP 1883 trên profile **Private**, giới hạn subnet, bằng PowerShell **Run as administrator**:

```powershell
New-NetFirewallRule -DisplayName 'IoT MQTT demo TCP 1883 Private LAN' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 1883 -Profile Private -RemoteAddress LocalSubnet
```

Lệnh này là tùy chọn và chưa được tự động chạy. Nó chỉ có hiệu lực với network profile Private; không chuyển mạng trường/công cộng sang Private chỉ để chạy demo. Gỡ quy tắc sau khi thử nếu đã thêm:

```powershell
Remove-NetFirewallRule -DisplayName 'IoT MQTT demo TCP 1883 Private LAN'
```

## 8. Xem log, dừng và lỗi thường gặp

```powershell
Set-Location 'E:\thieuh\FolderCode\IoT\Project'
docker compose -f .\deployment\mqtt_demo\compose.yaml logs -f --tail 50 mosquitto
```

`Ctrl+C` ở lệnh xem log chỉ thoát theo dõi. Dừng subscriber riêng bằng `Ctrl+C`, rồi dừng/xóa container và mạng của demo:

```powershell
docker compose -f .\deployment\mqtt_demo\compose.yaml down
```

- Không kết nối được Docker: mở Docker Desktop, đợi engine chạy và dùng Linux containers.
- `port is already allocated`: có chương trình/broker chiếm 1883; không dừng chương trình lạ. Kiểm tra `docker ps` và `Get-NetTCPConnection -LocalPort 1883 -State Listen`.
- `Connection refused`: broker chưa chạy, sai host/port, hoặc container khởi động lỗi; xem `ps` và `logs`.
- `ModuleNotFoundError: paho`: dùng đúng Python trong `backend/mqtt_demo/.venv` và chạy lại lệnh cài requirements.
- Không thấy `RX`: mở subscriber trước, chờ `READY`, kiểm tra topic khớp `devices/+/data` và cả hai client dùng cùng broker.
- Sau khi sửa `mosquitto.conf`, chạy `docker compose -f .\deployment\mqtt_demo\compose.yaml restart mosquitto` và kiểm tra log.
- Nếu đổi cổng host thành `1884:1883`, Python cần `--port 1884` và ESP32 cần `MQTT_PORT = 1884`; listener trong container vẫn là 1883.

## Tài liệu chính thức

- [Mosquitto: listener, anonymous và cấu hình](https://mosquitto.org/man/mosquitto-conf-5.html)
- [Eclipse Mosquitto Docker image](https://hub.docker.com/_/eclipse-mosquitto)
- [Paho Python client và callback API](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html)
- [Docker Compose networking](https://docs.docker.com/compose/how-tos/networking/)
- [MicroPython ESP32](https://docs.micropython.org/en/latest/esp32/quickref.html)
- [MicroPython: main.py và trình tự khởi động](https://docs.micropython.org/en/latest/reference/reset_boot.html)
- [mpremote: mount và run](https://docs.micropython.org/en/latest/reference/mpremote.html)
