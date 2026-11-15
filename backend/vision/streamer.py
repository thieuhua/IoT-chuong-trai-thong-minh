from __future__ import annotations

import logging
import threading
import time
from typing import Generator, Optional

import cv2
import numpy as np

from .analyzer import BehaviorSnapshot, BehaviorState, PetBehaviorAnalyzer
from .detector import PetDetector
from .visualizer import annotate_frame

logger = logging.getLogger("vision.streamer")


class CameraStreamer:
    """
    Quản lý luồng webcam trong background thread và xuất ra MJPEG stream cho web browser.
    """

    def __init__(
        self,
        source: int | str = 0,
        allow_person: bool = False,
        motionless_sec: float = 40.0,
        moving_threshold: float = 25.0,
    ):
        self.source = source
        self.allow_person = allow_person
        self.motionless_sec = motionless_sec
        self.moving_threshold = moving_threshold

        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        self._current_frame_bytes: Optional[bytes] = None
        self._latest_snapshot: Optional[BehaviorSnapshot] = None
        self._fps: float = 0.0

        self.detector: Optional[PetDetector] = None
        self.analyzer: Optional[PetBehaviorAnalyzer] = None

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info("Camera streamer started")

    def stop(self) -> None:
        self.running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        logger.info("Camera streamer stopped")

    def update_config(
        self,
        allow_person: Optional[bool] = None,
        motionless_sec: Optional[float] = None,
        moving_threshold: Optional[float] = None,
        source: Optional[int | str] = None,
    ) -> None:
        need_restart = False
        if source is not None and source != self.source:
            self.source = source
            need_restart = True
        if allow_person is not None and allow_person != self.allow_person:
            self.allow_person = allow_person
            need_restart = True

        if motionless_sec is not None:
            self.motionless_sec = motionless_sec
            if self.analyzer:
                self.analyzer.motionless_threshold_s = motionless_sec

        if moving_threshold is not None:
            self.moving_threshold = moving_threshold
            if self.analyzer:
                self.analyzer.moving_speed_threshold = moving_threshold

        if need_restart and self.running:
            self.stop()
            self.start()

    def get_latest_snapshot(self) -> Optional[dict]:
        with self._lock:
            if not self._latest_snapshot:
                return {
                    "is_running": self.running,
                    "state": "absent",
                    "label": "Khong phat hien",
                    "duration_s": 0.0,
                    "speed_px_s": 0.0,
                    "still_duration_s": 0.0,
                    "fps": round(self._fps, 1),
                    "class_name": None,
                    "confidence": 0.0,
                }
            s = self._latest_snapshot
            return {
                "is_running": self.running,
                "state": s.state.value,
                "label": s.label,
                "duration_s": s.duration_s,
                "speed_px_s": s.speed_px_s,
                "still_duration_s": s.still_duration_s,
                "fps": round(self._fps, 1),
                "class_name": s.class_name,
                "confidence": s.confidence,
                "box": s.box,
                "center": s.center,
                "timestamp": s.timestamp,
            }

    def _create_placeholder_frame(self, message: str) -> bytes:
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.rectangle(img, (20, 20), (620, 460), (40, 40, 40), 2)
        cv2.putText(img, "PET MONITOR CAMERA", (180, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)
        cv2.putText(img, message, (160, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 165, 255), 2)
        _, jpeg = cv2.imencode(".jpg", img)
        return jpeg.tobytes()

    def _capture_loop(self) -> None:
        try:
            self.detector = PetDetector(allow_person=self.allow_person)
            self.analyzer = PetBehaviorAnalyzer(
                moving_speed_threshold=self.moving_threshold,
                motionless_threshold_s=self.motionless_sec,
            )

            src = int(self.source) if str(self.source).isdigit() else self.source
            cap = cv2.VideoCapture(src)

            if not cap.isOpened():
                logger.error(f"Cannot open video source: {src}")
                placeholder = self._create_placeholder_frame(f"Khong mo duoc Camera: {src}")
                with self._lock:
                    self._current_frame_bytes = placeholder
                return

            prev_time = time.time()
            while self.running:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.1)
                    continue

                now = time.time()
                dt = now - prev_time
                if dt > 0:
                    self._fps = 0.9 * self._fps + 0.1 * (1.0 / dt) if self._fps > 0 else 1.0 / dt
                prev_time = now

                # Nhận diện & phân tích
                box, cls_name, conf = self.detector.detect(frame)
                snapshot = self.analyzer.update(
                    box=box,
                    class_name=cls_name,
                    confidence=conf,
                    now=now,
                )

                annotated = annotate_frame(frame, snapshot, trail=self.analyzer.trail, fps=self._fps)
                _, jpeg = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                jpeg_bytes = jpeg.tobytes()

                with self._lock:
                    self._current_frame_bytes = jpeg_bytes
                    self._latest_snapshot = snapshot

                # Ngủ nhẹ để tránh chiếm 100% CPU nếu camera fps quá cao
                time.sleep(0.01)

            cap.release()
        except Exception as e:
            logger.exception("Error in camera capture loop")
            placeholder = self._create_placeholder_frame(f"Loi Camera: {str(e)[:40]}")
            with self._lock:
                self._current_frame_bytes = placeholder

    def generate_mjpeg(self) -> Generator[bytes, None, None]:
        while True:
            with self._lock:
                frame_bytes = self._current_frame_bytes
            if frame_bytes is None:
                frame_bytes = self._create_placeholder_frame("Camera dang khoi dong...")

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )
            time.sleep(0.04)  # ~25 FPS
