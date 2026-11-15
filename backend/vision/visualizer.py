from __future__ import annotations

from typing import Deque, Optional, Tuple
import cv2
import numpy as np

from .analyzer import BehaviorSnapshot, BehaviorState


STATE_COLORS = {
    BehaviorState.WALKING: (50, 205, 50),     # Xanh lá cây (Lime Green)
    BehaviorState.RESTING: (235, 160, 52),    # Xanh dương / Cyan
    BehaviorState.MOTIONLESS: (0, 0, 230),    # Đỏ rực (Red Alert)
    BehaviorState.ABSENT: (140, 140, 140),    # Xám (Gray)
}


def annotate_frame(
    frame: np.ndarray,
    snapshot: BehaviorSnapshot,
    trail: Optional[Deque[Tuple[int, int]]] = None,
    fps: float = 0.0,
    show_trail: bool = False,
) -> np.ndarray:
    """
    Vẽ khung thông tin hành vi thú cưng lên hình ảnh:
    - Bounding box đổi màu theo trạng thái
    - Vết di chuyển (Trail - mặc định tắt để khung hình sạch đẹp)
    - Thanh trạng thái và cảnh báo (HUD)
    """
    out = frame.copy()
    h, w = out.shape[:2]

    color = STATE_COLORS.get(snapshot.state, (200, 200, 200))

    # 1. Vẽ vết di chuyển (Trail) nếu được bật
    if show_trail and trail and len(trail) > 1:
        points = list(trail)
        for i in range(1, len(points)):
            thickness = max(1, int(3 * (i / len(points))))
            cv2.line(out, points[i - 1], points[i], (0, 255, 255), thickness)

    # 2. Vẽ Bounding Box nếu có
    if snapshot.box is not None:
        x1, y1, x2, y2 = snapshot.box
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        # Khung viền chính
        thickness = 3 if snapshot.state == BehaviorState.MOTIONLESS else 2
        cv2.rectangle(out, (x1, y1), (x2, y2), color, thickness)

        # Nhãn đối tượng trên đầu box
        tag = f"{snapshot.class_name or 'pet'} {int(snapshot.confidence * 100)}%"
        (tag_w, tag_h), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(out, (x1, max(0, y1 - tag_h - 6)), (x1 + tag_w + 6, y1), color, -1)
        cv2.putText(
            out, tag, (x1 + 3, y1 - 4),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA,
        )

        # Tâm đối tượng
        if snapshot.center is not None:
            cv2.circle(out, snapshot.center, 4, color, -1)

    # 3. Vẽ Bảng điều khiển trạng thái (HUD Overlay ở góc trên bên trái)
    hud_h = 100
    hud_w = 360
    overlay = out.copy()
    cv2.rectangle(overlay, (10, 10), (10 + hud_w, 10 + hud_h), (25, 25, 25), -1)
    cv2.addWeighted(overlay, 0.75, out, 0.25, 0, out)
    cv2.rectangle(out, (10, 10), (10 + hud_w, 10 + hud_h), color, 2)

    # Dòng 1: Trạng thái hành vi
    status_text = f"HANH VI: {snapshot.label}"
    cv2.putText(out, status_text, (20, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)

    # Dòng 2: Thời gian duy trì trạng thái & Tốc độ
    detail_text = f"Thoi gian: {snapshot.duration_s:.1f}s | Toc do: {snapshot.speed_px_s:.1f} px/s"
    cv2.putText(out, detail_text, (20, 64), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1, cv2.LINE_AA)

    # Dòng 3: Thời gian đứng yên / FPS
    sub_text = f"Dung yen: {snapshot.still_duration_s:.1f}s"
    if fps > 0:
        sub_text += f" | FPS: {fps:.1f}"
    cv2.putText(out, sub_text, (20, 92), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1, cv2.LINE_AA)

    # 4. Banner cảnh báo nếu ở trạng thái BẤT ĐỘNG
    if snapshot.state == BehaviorState.MOTIONLESS:
        banner_text = f"! CANH BAO: THU CUNG BAT DONG > {int(snapshot.still_duration_s)}S !"
        (bw, bh), _ = cv2.getTextSize(banner_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        bx = max(10, (w - bw) // 2)
        by = h - 30
        cv2.rectangle(out, (bx - 10, by - bh - 8), (bx + bw + 10, by + 8), (0, 0, 200), -1)
        cv2.putText(out, banner_text, (bx, by), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)

    return out
