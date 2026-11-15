from __future__ import annotations

import enum
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, List, Optional, Tuple


class BehaviorState(str, enum.Enum):
    ABSENT = "absent"           # Không phát hiện thú cưng
    WALKING = "walking"         # Đi lại bình thường
    RESTING = "resting"         # Nghỉ ngơi (nằm/ngồi yên ổn định)
    MOTIONLESS = "motionless"   # Bất động (yên một chỗ quá ngưỡng cảnh báo)

    @property
    def label_vi(self) -> str:
        labels = {
            BehaviorState.ABSENT: "Khong phat hien",
            BehaviorState.WALKING: "Di lai binh thuong",
            BehaviorState.RESTING: "Nghi ngoi",
            BehaviorState.MOTIONLESS: "BAT DONG (CANH BAO)",
        }
        return labels.get(self, str(self.value))


@dataclass
class BehaviorSnapshot:
    state: BehaviorState
    label: str
    duration_s: float
    speed_px_s: float
    still_duration_s: float
    box: Optional[Tuple[int, int, int, int]]
    center: Optional[Tuple[int, int]]
    class_name: Optional[str]
    confidence: float
    timestamp: float


class PetBehaviorAnalyzer:
    """
    Phân tích hành vi thú cưng dựa trên bounding box theo thời gian:
    - Đi lại bình thường: Vận tốc di chuyển > moving_threshold
    - Nghỉ ngơi: Vận tốc di chuyển <= moving_threshold trong thời gian < motionless_threshold_s
    - Bất động: Không di chuyển liên tục trong thời gian >= motionless_threshold_s
    - Không phát hiện: Mất dấu thú cưng quá absent_timeout_s
    """

    def __init__(
        self,
        moving_speed_threshold: float = 25.0,  # pixels / giây
        motionless_threshold_s: float = 40.0,  # giây đứng yên liên tục để coi là bất động bất thường
        absent_timeout_s: float = 2.5,        # giây không thấy để coi là vắng mặt
        window_sec: float = 1.5,              # cửa sổ tính vận tốc trung bình
        on_state_change: Optional[Callable[[BehaviorState, BehaviorState, BehaviorSnapshot], None]] = None,
    ):
        self.moving_speed_threshold = moving_speed_threshold
        self.motionless_threshold_s = motionless_threshold_s
        self.absent_timeout_s = absent_timeout_s
        self.window_sec = window_sec
        self.on_state_change = on_state_change

        self.current_state = BehaviorState.ABSENT
        self.state_start_time: float = 0.0
        self.still_start_time: Optional[float] = None
        self.last_seen_time: Optional[float] = None

        # Lưu lịch sử (timestamp, cx, cy) trong khoảng window_sec
        self._history: Deque[Tuple[float, float, float]] = deque()
        # Vết di chuyển để vẽ visualizer (tối đa 40 điểm)
        self.trail: Deque[Tuple[int, int]] = deque(maxlen=40)

        self._last_snapshot: Optional[BehaviorSnapshot] = None

    def update(
        self,
        box: Optional[Tuple[int, int, int, int]],
        class_name: Optional[str] = None,
        confidence: float = 0.0,
        now: Optional[float] = None,
    ) -> BehaviorSnapshot:
        if now is None:
            now = time.time()

        if self.state_start_time == 0.0:
            self.state_start_time = now

        # 1. Trường hợp không phát hiện được thú cưng trong frame
        if box is None:
            if self.last_seen_time is None or (now - self.last_seen_time) >= self.absent_timeout_s:
                new_state = BehaviorState.ABSENT
                self.still_start_time = None
                self._history.clear()
                self._set_state(new_state, now)
                return self._build_snapshot(
                    state=new_state,
                    duration_s=now - self.state_start_time,
                    speed_px_s=0.0,
                    still_duration_s=0.0,
                    box=None,
                    center=None,
                    class_name=None,
                    confidence=0.0,
                    now=now,
                )
            else:
                # Trong thời gian ân hạn (chưa quá absent_timeout_s), giữ trạng thái cũ
                return self._last_snapshot or self._build_snapshot(
                    state=self.current_state,
                    duration_s=now - self.state_start_time,
                    speed_px_s=0.0,
                    still_duration_s=0.0,
                    box=None,
                    center=None,
                    class_name=class_name,
                    confidence=confidence,
                    now=now,
                )

        # 2. Phát hiện thấy thú cưng
        self.last_seen_time = now
        x1, y1, x2, y2 = box
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        self.trail.append((int(cx), int(cy)))
        self._history.append((now, cx, cy))

        # Loại bỏ các điểm ngoài cửa sổ window_sec
        cutoff = now - self.window_sec
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()

        # Tính vận tốc trung bình (px / giây)
        speed_px_s = self._calculate_speed(now)

        # 3. Phân định trạng thái
        if speed_px_s > self.moving_speed_threshold:
            # Đang di chuyển -> Đi lại bình thường
            new_state = BehaviorState.WALKING
            self.still_start_time = None
            still_duration = 0.0
        else:
            # Đang đứng yên/ít di chuyển
            if self.still_start_time is None:
                self.still_start_time = now
            still_duration = now - self.still_start_time

            if still_duration >= self.motionless_threshold_s:
                # Yên quá thời gian cho phép -> Bất động
                new_state = BehaviorState.MOTIONLESS
            else:
                # Dưới ngưỡng bất động -> Nghỉ ngơi
                new_state = BehaviorState.RESTING

        self._set_state(new_state, now)

        snapshot = self._build_snapshot(
            state=new_state,
            duration_s=now - self.state_start_time,
            speed_px_s=speed_px_s,
            still_duration_s=still_duration,
            box=box,
            center=(int(cx), int(cy)),
            class_name=class_name,
            confidence=confidence,
            now=now,
        )
        self._last_snapshot = snapshot
        return snapshot

    def _calculate_speed(self, now: float) -> float:
        if len(self._history) < 2:
            return 0.0

        t_first, x_first, y_first = self._history[0]
        t_last, x_last, y_last = self._history[-1]
        dt = t_last - t_first
        if dt <= 0.01:
            return 0.0

        # Khoảng cách Euclide giữa vị trí đầu và cuối cửa sổ
        dist = math.hypot(x_last - x_first, y_last - y_first)
        return dist / dt

    def _set_state(self, new_state: BehaviorState, now: float) -> None:
        if new_state != self.current_state:
            old_state = self.current_state
            self.current_state = new_state
            self.state_start_time = now

            if self.on_state_change and self._last_snapshot:
                self.on_state_change(old_state, new_state, self._last_snapshot)

    def _build_snapshot(
        self,
        state: BehaviorState,
        duration_s: float,
        speed_px_s: float,
        still_duration_s: float,
        box: Optional[Tuple[int, int, int, int]],
        center: Optional[Tuple[int, int]],
        class_name: Optional[str],
        confidence: float,
        now: float,
    ) -> BehaviorSnapshot:
        return BehaviorSnapshot(
            state=state,
            label=state.label_vi,
            duration_s=round(duration_s, 1),
            speed_px_s=round(speed_px_s, 1),
            still_duration_s=round(still_duration_s, 1),
            box=box,
            center=center,
            class_name=class_name,
            confidence=round(confidence, 2),
            timestamp=now,
        )
