# Điều khiển servo từ điện thoại

Điện thoại mở trang demo qua Wi-Fi. Trang gọi server demo, server gửi lệnh
`servo_set` tới FastAPI đang chạy trên laptop. FastAPI chuyển lệnh qua
Mosquitto tới ESP32. Dùng firmware và broker hiện tại.

1. Giữ ESP32, Mosquitto và FastAPI đang chạy. Trong Swagger
   (`http://localhost:8000/docs`), dùng `GET /devices` để xác nhận
   board online và lấy `device_id`.
2. Cho điện thoại vào cùng hotspot với ESP32. Chạy từ thư mục dự án trong
   PowerShell. Thay địa chỉ bind nếu IP hotspot của laptop khác.

   ```powershell
   .\backend\.venv\Scripts\python.exe -B .\demo\servo_slider\server.py --device esp32-383e51cb0328 --bind 192.168.137.1
   ```

3. Trên điện thoại, mở `http://192.168.137.1:8081`. Kéo thanh trượt
   để gửi góc ngay trong lúc kéo, hoặc chạm một góc đặt sẵn. Giao diện hiển thị góc mục tiêu và
   báo khi ESP32 phản hồi. Lệnh quay một góc dừng chuỗi góc đang chạy
   trên servo. Trang kiểm tra mẫu nhiệt độ và độ ẩm mới nhất mỗi 2 giây.
   Thời điểm hiển thị là lúc backend nhận mẫu.

Hai thẻ Relay bật/tắt relay ở G26 (`relay`) và G27 (`relay2`) bằng lệnh `relay_set`, đọc
trạng thái bằng `actuator_state` mỗi 2–5 giây. Hai relay điều khiển độc lập. Chọn "Tự tắt sau"
trước khi bật để relay tự tắt trên ESP32, kể cả khi mất mạng. Cần firmware có driver relay và hai
mục `relay`, `relay2` trong `config.json` (xem `firmware/config.example.json`).

Server tự ký token của một tài khoản Admin đang hoạt động bằng `JWT_SECRET_KEY` trong
`deployment/.env` (cần `DATABASE_URL` để tìm tài khoản), làm mới trước khi hết hạn và không gửi
token về điện thoại. `--admin <username>` chọn tài khoản Admin cụ thể. Vì vậy ai mở được trang
cũng điều khiển được thiết bị với quyền Admin; chỉ chạy trên hotspot riêng.

Server mặc định chuyển tiếp đến FastAPI ở cổng 8000. Dùng `--api-port`
nếu FastAPI chạy cổng khác, `--actuator` nếu tên servo khác `servo`,
`--sensor` nếu tên cảm biến khác `room`, `--relay` và `--relay2` nếu tên hai relay khác
`relay`, `relay2`.
Nếu điện thoại không mở được trang, kiểm tra IP hotspot và quyền truy cập
TCP 8081 trong Windows Firewall. Demo dành cho hotspot riêng vì trang
điều khiển không có đăng nhập. Nhấn Ctrl+C để dừng server demo.
