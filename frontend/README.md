# Giao Diện Web React - Smart Barn & Pet AI Monitor

Giao diện Web React được xây dựng bằng **Vite + React 18**, tích hợp trực tiếp với Backend FastAPI và Camera AI.

## Các chức năng chính
1. **Camera AI Thú Cưng**:
   - Xem luồng hình ảnh trực tiếp (Live Stream MJPEG) từ webcam laptop hoặc camera IP/smartphone.
   - Hiển thị nhãn trạng thái theo thời gian thực:
     - 🟢 **Đi lại bình thường** (`WALKING`)
     - 🔵 **Nghỉ ngơi** (`RESTING`)
     - 🔴 **BẤT ĐỘNG - CẢNH BÁO** (`MOTIONLESS`)
     - ⚪ **Không phát hiện** (`ABSENT`)
   - Bảng đo lường: Vận tốc di chuyển (px/s), Thời gian đứng yên liên tục (s), FPS.
   - Điều khiển nhanh: Bật/Tắt camera, chuyển chế độ test Người/Tay (`allow-person`), chỉnh ngưỡng thời gian báo động bất động (5s, 10s, 20s, 30s).
   - Nút **"Cho Ăn Ngay"**: Gửi lệnh MQTT tới ESP32 xoay Servo nhả thức ăn.
   - **Nhật ký hoạt động**: Lưu vết các mốc thời gian chuyển trạng thái của thú cưng.

2. **Thiết Bị & Cảm Biến Chuồng Trại**:
   - Giám sát danh sách board ESP32 (Online/Offline, MAC hw_id).
   - Đọc nhiệt độ, độ ẩm và các chỉ số môi trường.
   - Thao tác gửi lệnh trực tiếp: Ping, Xoay máng ăn, Khởi động lại.

3. **Phê Duyệt Thiết Bị (Provisioning)**:
   - Danh sách các board ESP32 mới đang chờ duyệt (`/registrations`).
   - Duyệt hoặc từ chối thiết bị chỉ với một cú click chuột.

---

## Hướng dẫn khởi chạy

### Bước 1: Khởi động Backend (cổng 8000)
Mở một terminal tại thư mục gốc của dự án:
```bash
cd backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Bước 2: Khởi động Giao diện Frontend (cổng 5173)
Mở một terminal khác tại thư mục `frontend/`:
```bash
cd frontend
npm run dev
```

Sau đó mở trình duyệt truy cập: **`http://localhost:5173`**
