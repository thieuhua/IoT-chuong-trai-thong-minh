from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Tuple

# Đảm bảo Ultralytics không ghi vào thư mục cấm trên hệ thống
os.environ.setdefault("YOLO_CONFIG_DIR", "/tmp/Ultralytics")

import numpy as np
from ultralytics import YOLO


class PetDetector:
    """
    Phát hiện thú cưng (chó/mèo) sử dụng mô hình YOLOv8n tiền huấn luyện trên COCO.
    Hỗ trợ bật thêm class 'person' để thuận tiện kiểm thử khi không có thú cưng thật.
    """

    CLASS_NAMES = {
        0: "person",
        15: "cat",
        16: "dog",
    }

    def __init__(
        self,
        model_path: Optional[str] = None,
        conf_threshold: float = 0.45,
        allow_person: bool = False,
    ):
        if model_path is None:
            # Mặc định tìm model ở backend/yolov8n.pt hoặc trong thư mục vision
            candidates = [
                Path(__file__).parent.parent / "yolov8n.pt",
                Path(__file__).parent / "yolov8n.pt",
                Path("yolov8n.pt"),
            ]
            for p in candidates:
                if p.is_file():
                    model_path = str(p.resolve())
                    break
            if model_path is None:
                model_path = "yolov8n.pt"

        self.model = YOLO(model_path)
        self.conf_threshold = conf_threshold
        self.allow_person = allow_person

        # Lựa chọn class IDs cần nhận diện: 15=cat, 16=dog. Thêm 0=person nếu allow_person=True
        self.target_classes = [15, 16]
        if self.allow_person:
            self.target_classes.append(0)

    def detect(self, frame: np.ndarray) -> Tuple[Optional[Tuple[int, int, int, int]], Optional[str], float]:
        """
        Nhận diện đối tượng trong frame.
        Trả về: (box=(x1, y1, x2, y2), class_name, confidence)
        Nếu có nhiều đối tượng, trả về đối tượng có độ tin cậy cao nhất.
        """
        results = self.model.predict(
            source=frame,
            classes=self.target_classes,
            conf=self.conf_threshold,
            verbose=False,
        )

        if not results or len(results[0].boxes) == 0:
            return None, None, 0.0

        boxes = results[0].boxes
        # Chọn box có confidence cao nhất
        best_idx = int(boxes.conf.argmax())
        best_box = boxes.xyxy[best_idx].cpu().numpy().astype(int)
        best_conf = float(boxes.conf[best_idx].cpu().numpy())
        cls_id = int(boxes.cls[best_idx].cpu().numpy())

        class_name = self.CLASS_NAMES.get(cls_id, self.model.names.get(cls_id, f"obj_{cls_id}"))
        x1, y1, x2, y2 = best_box.tolist()

        return (x1, y1, x2, y2), class_name, best_conf
