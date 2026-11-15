# Dockerfile for Backend FastAPI + OpenCV + YOLO
FROM python:3.12-slim

WORKDIR /app

# Cài đặt thư viện hệ thống cần thiết cho OpenCV và hình ảnh
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Cấu hình biến môi trường cho YOLO
ENV YOLO_CONFIG_DIR=/tmp/Ultralytics
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
