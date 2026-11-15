#!/usr/bin/env python3
"""
Tool chạy nhận diện và phân tích hành vi thú cưng trực tiếp qua Webcam/Video.

Ví dụ chạy:
  # Chạy bình thường với webcam laptop (nhận diện chó/mèo):
  python3 tools/pet_monitor.py

  # Test không có thú cưng thật (cho phép nhận diện người/tay để thử logic):
  python3 tools/pet_monitor.py --allow-person

  # Chỉnh thời gian bất động xuống 5 giây để test nhanh:
  python3 tools/pet_monitor.py --allow-person --motionless-sec 5

  # Chạy với một file video có sẵn:
  python3 tools/pet_monitor.py --source /path/to/video.mp4
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Đảm bảo import được backend.vision
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import cv2
from vision.analyzer import PetBehaviorAnalyzer, BehaviorState, BehaviorSnapshot
from vision.detector import PetDetector
from vision.visualizer import annotate_frame


def on_behavior_changed(old_state: BehaviorState, new_state: BehaviorState, snapshot: BehaviorSnapshot) -> None:
    timestamp_str = time.strftime("%H:%M:%S")
    symbols = {
        BehaviorState.WALKING: "🟢 [DI LAI BINH THUONG]",
        BehaviorState.RESTING: "🔵 [NGHI NGOI]",
        BehaviorState.MOTIONLESS: "🔴 [CANH BAO: BAT DONG]",
        BehaviorState.ABSENT: "⚪ [KHONG PHAT HIEN]",
    }
    sym = symbols.get(new_state, str(new_state))
    print(f"[{timestamp_str}] Chuyen trang thai: {old_state.name} -> {sym} (toc do: {snapshot.speed_px_s} px/s, dung yen: {snapshot.still_duration_s}s)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Theo doi hanh vi thu cung qua Camera AI")
    parser.add_argument("--source", default="0", help="Nguon camera: 0 cho webcam mac dinh hoac duong dan toi video .mp4")
    parser.add_argument("--allow-person", action="store_true", help="Cho phep nhan dien nguoi (person) lam vat the test khi khong co thu cung")
    parser.add_argument("--motionless-sec", type=float, default=40.0, help="So giay dung yen lien tuc de kich hoat trang thai BAT DONG (mac dinh: 40s)")
    parser.add_argument("--moving-threshold", type=float, default=25.0, help="Nguong toc do (px/s) de xep vao DI LAI BINH THUONG (mac dinh: 25 px/s)")
    parser.add_argument("--headless", action="store_true", help="Chay khong hien thi cua so GUI (cho moi truong server/test)")
    parser.add_argument("--max-frames", type=int, default=0, help="Dung lai sau so luong frame nay (0: chay vo han)")
    parser.add_argument("--save", type=str, default="", help="Luu video da xu ly ra file .mp4")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Xử lý nguồn camera
    src = int(args.source) if args.source.isdigit() else args.source
    print("=" * 60)
    print("🐾 HE THONG THEO DOI HANH VI THU CUNG (AI VISION)")
    print(f"  • Nguon Camera: {src}")
    print(f"  • Che do test nguoi (--allow-person): {'BAT' if args.allow_person else 'TAT (Chi cho/meo)'}")
    print(f"  • Nguong bat dong: {args.motionless_sec} giay")
    print(f"  • Nguong di chuyen: {args.moving_threshold} px/s")
    print("=" * 60)

    # Khởi tạo detector & analyzer
    detector = PetDetector(allow_person=args.allow_person)
    analyzer = PetBehaviorAnalyzer(
        moving_speed_threshold=args.moving_threshold,
        motionless_threshold_s=args.motionless_sec,
        on_state_change=on_behavior_changed,
    )

    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        print(f"❌ Khong the mo nguon camera: {src}", file=sys.stderr)
        return 1

    writer = None
    if args.save:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        fps_in = cap.get(cv2.CAP_PROP_FPS) or 25.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        writer = cv2.VideoWriter(args.save, fourcc, fps_in, (w, h))
        print(f"📹 Dang ghi hinh vao file: {args.save}")

    frame_count = 0
    prev_time = time.time()
    fps = 0.0

    print("🚀 He thong dang chay. Nhan 'q' tren cua so video hoac Ctrl+C de thoat.")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("🏁 Ket thuc luong video hoac khong nhan duoc frame.")
                break

            now = time.time()
            dt = now - prev_time
            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps > 0 else 1.0 / dt
            prev_time = now

            # 1. Phát hiện đối tượng
            box, cls_name, conf = detector.detect(frame)

            # 2. Cập nhật phân tích hành vi
            snapshot = analyzer.update(
                box=box,
                class_name=cls_name,
                confidence=conf,
                now=now,
            )

            # 3. Vẽ thông tin lên frame
            annotated = annotate_frame(frame, snapshot, trail=analyzer.trail, fps=fps)

            if writer:
                writer.write(annotated)

            frame_count += 1
            if args.max_frames > 0 and frame_count >= args.max_frames:
                print(f"Dat gioi han {args.max_frames} frame. Dung chuong trinh.")
                break

            # 4. Hiển thị GUI nếu không bật headless
            if not args.headless:
                cv2.imshow("Pet Behavior Monitor", annotated)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q") or key == 27:
                    print("Nguoi dung bam 'q' thoat.")
                    break

    except KeyboardInterrupt:
        print("\nNhan tin hieu dung (Ctrl+C).")
    finally:
        cap.release()
        if writer:
            writer.release()
        if not args.headless:
            cv2.destroyAllWindows()

    print("✅ Da ket thuc phien theo doi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
