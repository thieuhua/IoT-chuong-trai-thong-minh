from vision.analyzer import PetBehaviorAnalyzer, BehaviorState


def test_initial_state_absent():
    analyzer = PetBehaviorAnalyzer()
    snapshot = analyzer.update(box=None, now=100.0)
    assert snapshot.state == BehaviorState.ABSENT


def test_walking_state():
    analyzer = PetBehaviorAnalyzer(moving_speed_threshold=20.0, window_sec=1.0)

    # Khung hình 1: vị trí (100, 100)
    s1 = analyzer.update(box=(90, 90, 110, 110), class_name="dog", confidence=0.9, now=1.0)
    # Chưa đủ 2 điểm trong cửa sổ -> speed=0, tạm thời RESTING
    assert s1.state == BehaviorState.RESTING

    # Khung hình 2: vị trí (200, 100) sau 0.5s -> di chuyển 100px trong 0.5s = 200 px/s (> 20.0)
    s2 = analyzer.update(box=(190, 90, 210, 110), class_name="dog", confidence=0.9, now=1.5)
    assert s2.state == BehaviorState.WALKING
    assert s2.speed_px_s > 100.0
    assert s2.label == "Di lai binh thuong"


def test_resting_to_motionless_transition():
    state_transitions = []

    def on_change(old_state, new_state, snapshot):
        state_transitions.append((old_state, new_state))

    analyzer = PetBehaviorAnalyzer(
        moving_speed_threshold=20.0,
        motionless_threshold_s=5.0,  # 5s đứng yên -> MOTIONLESS
        window_sec=1.0,
        on_state_change=on_change,
    )

    t = 10.0
    # Đi lại bình thường
    analyzer.update(box=(100, 100, 150, 150), class_name="cat", confidence=0.85, now=t)
    t += 0.5
    s_walk = analyzer.update(box=(160, 100, 210, 150), class_name="cat", confidence=0.85, now=t)
    assert s_walk.state == BehaviorState.WALKING

    # Dừng lại ở vị trí (160, 100, 210, 150), sau khi qua cửa sổ trượt 1.0s
    t += 1.1
    s_rest = analyzer.update(box=(160, 100, 210, 150), class_name="cat", confidence=0.85, now=t)
    assert s_rest.state == BehaviorState.RESTING
    assert s_rest.label == "Nghi ngoi"

    # Đứng yên tiếp tục 3.5 giây nữa (tổng đứng yên: 1.1 + 3.5 = 4.6s < 5.0s) -> Vẫn là RESTING
    t += 3.5
    s_rest2 = analyzer.update(box=(160, 100, 210, 150), class_name="cat", confidence=0.85, now=t)
    assert s_rest2.state == BehaviorState.RESTING
    assert s_rest2.still_duration_s < 5.0

    # Đứng yên thêm 2.0 giây nữa (tổng đứng yên: 3.5 + 2.0 = 5.5s >= 5.0s) -> Chuyển sang MOTIONLESS (Bất động)
    t += 2.0
    s_motionless = analyzer.update(box=(160, 100, 210, 150), class_name="cat", confidence=0.85, now=t)
    assert s_motionless.state == BehaviorState.MOTIONLESS
    assert s_motionless.label == "BAT DONG (CANH BAO)"
    assert s_motionless.still_duration_s >= 5.0

    # Nếu sau đó bắt đầu di chuyển lại -> Chuyển về WALKING
    t += 0.5
    s_walk2 = analyzer.update(box=(250, 100, 300, 150), class_name="cat", confidence=0.85, now=t)
    assert s_walk2.state == BehaviorState.WALKING
    assert s_walk2.still_duration_s == 0.0


def test_absent_timeout():
    analyzer = PetBehaviorAnalyzer(absent_timeout_s=2.0)
    t = 1.0
    # Thấy thú cưng
    analyzer.update(box=(100, 100, 150, 150), class_name="cat", confidence=0.9, now=t)

    # 1 giây sau không thấy -> Vẫn giữ trạng thái cũ (trong thời gian ân hạn)
    t += 1.0
    s_grace = analyzer.update(box=None, now=t)
    assert s_grace.state != BehaviorState.ABSENT

    # 2.5 giây sau không thấy -> Quá timeout -> Chuyển sang ABSENT
    t += 1.5
    s_absent = analyzer.update(box=None, now=t)
    assert s_absent.state == BehaviorState.ABSENT


if __name__ == "__main__":
    test_initial_state_absent()
    print("PASS: test_initial_state_absent")
    test_walking_state()
    print("PASS: test_walking_state")
    test_resting_to_motionless_transition()
    print("PASS: test_resting_to_motionless_transition")
    test_absent_timeout()
    print("PASS: test_absent_timeout")
    print("\n🎉 === ALL PET BEHAVIOR TESTS PASSED ===")

