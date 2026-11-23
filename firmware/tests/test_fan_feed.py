import json
import time

import pytest

from app import App
from core import protocol as p, session
from test_commands import invoke
import commands


@pytest.fixture
def farm(ctx, monkeypatch):
    config = dict(ctx.config, sensors=[dict(driver="simulated", name="room")],
                  fan_control=dict(sensor="room", relay="relay", on_c=32, off_c=30,
                                   fault_reads=3, manual_ttl_min=1),
                  actuators=[dict(driver="relay", name="relay", pin=26),
                             dict(driver="relay", name="lamp", pin=27),
                             dict(driver="servo", name="servo", pin=14, initial=90,
                                  max_dps=360)], feed_limit_per_day=2)
    app = App(config, ctx.identity)
    app.link = ctx.link
    readings = {"temperature": 29, "calls": 0, "broken": False}

    def measure():
        readings["calls"] += 1
        if readings["broken"]:
            raise OSError("timeout")
        return {"temperature": readings["temperature"], "humidity": 70}

    monkeypatch.setattr(app.fan_control.sensor, "_measure", measure)
    yield app, readings
    app._timer.deinit()


def sample(farm, elapsed, temperature=None, broken=False):
    app, readings = farm
    if temperature is not None:
        readings["temperature"] = temperature
    readings["broken"] = broken
    elapsed[0] += 2000
    app.control_tick()


def test_fan_hysteresis_rate_limit_and_telemetry(farm, board_environment):
    app, readings = farm
    app.control_tick()
    sample(farm, board_environment, 32)
    assert app.actuator("relay").on
    for _ in range(50):
        app.feed()
        app.control_tick()
        app.read_sensors()
        app._timer.fire()
    assert readings["calls"] == 2
    assert app.read_sensors() == dict(readings={"room": dict(temperature=32, humidity=70)},
                                      mode="AUTO", fan_on=True, sensor_ok=True)
    sample(farm, board_environment, 31)
    assert app.actuator("relay").on
    sample(farm, board_environment, 30)
    assert not app.actuator("relay").on
    sample(farm, board_environment, 31)
    assert not app.actuator("relay").on


def test_manual_ttl_and_mode_set(farm, board_environment):
    app, _ = farm
    sample(farm, board_environment, 36)
    assert invoke(app, "relay_set", dict(name="relay", on=False))["ok"]
    assert app.fan_control.mode == "MANUAL"
    board_environment[0] += 59999
    app.feed()
    assert not app.actuator("relay").on
    board_environment[0] += 1
    app.feed()
    assert app.actuator("relay").on and app.fan_control.mode == "AUTO"
    assert invoke(app, "mode_set", dict(mode="manual"))["result"]["mode"] == "MANUAL"
    assert invoke(app, "mode_set", dict(mode="auto"))["result"]["mode"] == "AUTO"
    assert invoke(app, "mode_set", dict(mode="AUTO"))["error"]["code"] == "bad_args"


def test_three_faults_override_manual_and_timers_then_recover(farm, board_environment):
    app, _ = farm
    relay = app.actuator("relay")
    relay.max_on_ms = 100
    invoke(app, "relay_set", dict(name="relay", on=False))
    for _ in range(2):
        sample(farm, board_environment, broken=True)
        assert not relay.on
    sample(farm, board_environment, broken=True)
    assert relay.on and not app.fan_control.sensor_ok
    assert invoke(app, "relay_set", dict(name="relay", on=False))["error"]["code"] == "sensor_error"
    assert invoke(app, "relay_set", dict(name="relay", on=True, duration_ms=100))["ok"]
    board_environment[0] += 200
    app._timer.fire()
    assert relay.on
    with pytest.raises(ValueError):
        relay.set(False)
    assert app.read_sensors()["errors"] == {"room": "timeout"}
    assert invoke(app, "relay_set", dict(name="lamp", on=False))["ok"]
    sample(farm, board_environment, 29)
    assert app.fan_control.sensor_ok
    assert invoke(app, "relay_set", dict(name="relay", on=False))["ok"]


def test_good_read_resets_fault_streak_and_nan_is_fault(farm, board_environment):
    app, _ = farm
    sample(farm, board_environment, broken=True)
    sample(farm, board_environment, broken=True)
    sample(farm, board_environment, 29)
    assert app.fan_control.failures == 0
    sample(farm, board_environment, float("nan"))
    assert app.fan_control.failures == 1 and not app.actuator("relay").on


def test_control_runs_during_mqtt_recovery(farm, monkeypatch, board_environment):
    app, readings = farm
    readings["broken"] = True
    attempts = []

    def offline(ctx):
        attempts.append(1)
        if len(attempts) == 3:
            assert ctx.actuator("relay").on
            raise KeyboardInterrupt()
        raise OSError("MQTT offline")

    monkeypatch.setattr(session, "run", offline)
    with pytest.raises(KeyboardInterrupt):
        app.run()
    assert board_environment[0] >= 6000


def test_manual_ttl_across_tick_wrap(farm, board_environment):
    app, readings = farm
    board_environment[0] = (1 << 30) - 1000
    readings["temperature"] = 36
    invoke(app, "relay_set", dict(name="relay", on=False))
    board_environment[0] += 60000
    app.feed()
    assert app.fan_control.mode == "AUTO" and app.actuator("relay").on


def test_fan_reads_only_from_cooperative_loop(farm):
    app, readings = farm
    app._timer.fire()
    assert readings["calls"] == 0
    app.feed()
    assert readings["calls"] == 1


def feed_command(app, command_id="feed-1", seconds=1):
    commands.dispatch(app, p.encode(p.CMD, dict(name="feed", args=dict(seconds=seconds)), command_id))
    return json.loads(app.link.client.publishes[-1][1])["data"]


def test_feed_waits_for_motion_closes_before_response_and_feeds_watchdog(farm, board_environment):
    import machine
    app, readings = farm
    app.watchdog = machine.WDT(timeout=1000)
    readings["temperature"] = 36
    result = feed_command(app)
    servo = app.actuator("servo")
    assert result == dict(re="feed-1", ok=True, result=dict(seconds=1, angle=90, feed_count=1))
    assert servo.position == servo.angle == 90 and not servo.running
    assert 1400 <= board_environment[0] < 2000  # 1 s open + 2 x 80 deg at 360 deg/s
    assert app.watchdog.feeds >= 20 and app.actuator("relay").on
    assert len(set(servo.pwm.duty_values)) > 4  # both travel directions were driven


def test_feed_replay_after_lost_response_never_moves_twice(farm, monkeypatch, board_environment):
    app, _ = farm
    publish = app.publish
    monkeypatch.setattr(app, "publish", lambda *a, **kw: (_ for _ in ()).throw(OSError("lost resp")))
    with pytest.raises(OSError, match="lost resp"):
        feed_command(app)
    elapsed = board_environment[0]
    writes = list(app.actuator("servo").pwm.duty_values)
    monkeypatch.setattr(app, "publish", publish)
    assert feed_command(app)["ok"]
    assert board_environment[0] == elapsed and app.feed_count == 1
    assert app.actuator("servo").pwm.duty_values == writes


def test_feed_daily_limit_and_reset_by_uptime(farm, board_environment):
    app, _ = farm
    assert feed_command(app, "a")["ok"]
    assert feed_command(app, "b")["ok"]
    assert feed_command(app, "c")["error"]["code"] == "feed_limit"
    assert app.feed_count == 2
    board_environment[0] = 86400000
    assert feed_command(app, "d")["ok"] and app.feed_count == 1
    # A rejected command's replay must not start feeding after the day changed.
    assert feed_command(app, "c")["error"]["code"] == "feed_limit"
    assert app.feed_count == 1


@pytest.mark.parametrize("seconds", [None, True, 0, 11, -1, 1.5, "1"])
def test_feed_bad_seconds_do_not_move_or_count(farm, seconds):
    app, _ = farm
    assert feed_command(app, seconds=seconds)["error"]["code"] == "bad_args"
    assert app.feed_count == 0 and app.actuator("servo").position == 90


def test_feed_replay_cache_is_bounded(farm):
    app, _ = farm
    for i in range(12):
        feed_command(app, str(i), 0)
    assert len(app.feed_responses) == 8


def test_feed_closes_after_error_during_hold(farm, monkeypatch):
    app, _ = farm
    original = commands.pause

    def fail(seconds, feed):
        feed()
        raise OSError("interrupted")

    monkeypatch.setattr(commands, "pause", fail)
    assert feed_command(app)["error"]["code"] == "internal"
    assert app.feed_count == 1 and app.actuator("servo").position == 90
    monkeypatch.setattr(commands, "pause", original)
    assert feed_command(app)["error"]["code"] == "internal"
    assert app.feed_count == 1


def test_feed_uses_configured_angle_and_zero_means_no_slew(farm):
    app, _ = farm
    app.config["feed_open_angle"] = 60
    servo = app.actuator("servo")
    servo.max_dps = 0
    observed = []
    original = servo.set_angle

    def set_angle(angle):
        observed.append(angle)
        original(angle)

    servo.set_angle = set_angle
    assert feed_command(app)["ok"]
    assert observed == [60, 90] and servo.position == 90


def test_feed_limit_uptime_survives_ticks_wrap(farm, board_environment):
    app, _ = farm
    # Accumulate days through regular calls rather than subtracting boot ticks forever.
    for _ in range(14):
        board_environment[0] += 86400000
        app.feed()
    assert board_environment[0] > (1 << 30)
    assert feed_command(app)["ok"]
    assert feed_command(app, "next")["ok"]
    assert feed_command(app, "limit")["error"]["code"] == "feed_limit"


def test_local_telemetry_samples_trip_safety_without_double_counting_reads(farm, board_environment):
    app, readings = farm
    for _ in range(3):
        app.publish(p.TELEMETRY, dict(readings={}, errors={"room": "timeout"}))
    assert app.actuator("relay").on and readings["calls"] == 0
    # Transmitting a sampled error (including retransmission) is not a fresh read.
    app.fan_control.failures = 0
    readings["broken"] = True
    board_environment[0] += 2000
    data = app.read_sensors()
    assert app.fan_control.failures == 1
    app.publish(p.TELEMETRY, data)
    app.publish(p.TELEMETRY, data)
    assert app.fan_control.failures == 1


@pytest.mark.parametrize("seconds", [1, 8, 9, 10])
def test_feed_respects_default_backend_timeout(farm, seconds, board_environment):
    app, _ = farm
    response = feed_command(app, seconds=seconds)
    if seconds >= 9:
        assert response["error"]["code"] == "bad_args"
        assert app.feed_count == 0 and app.actuator("servo").position == 90
    else:
        assert response["ok"] and app.actuator("servo").position == 90
    assert board_environment[0] < 10000


def test_feed_rejects_slow_servo_before_moving(farm, board_environment):
    app, _ = farm
    app.actuator("servo").max_dps = 1
    assert feed_command(app)["error"]["code"] == "bad_args"
    assert app.feed_count == 0 and board_environment[0] == 0


def test_feed_motion_timeout_is_bounded_and_replayed(farm, monkeypatch, board_environment):
    app, _ = farm
    # Servo opens normally, then a fault prevents the closing slew from progressing.
    servo = app.actuator("servo")
    original = servo.tick

    def tick(now):
        if servo.angle != 90:
            original(now)

    monkeypatch.setattr(servo, "tick", tick)
    result = feed_command(app)
    assert result["error"]["code"] == "internal"
    assert servo.angle == 90 and board_environment[0] <= commands.FEED_BUDGET_MS + 20
    assert feed_command(app) == result and app.feed_count == 1


def test_feed_default_opens_at_10_and_closes_at_90(farm):
    app, _ = farm
    servo = app.actuator("servo")
    observed = []
    original = servo.set_angle

    def set_angle(angle):
        observed.append(angle)
        original(angle)

    servo.set_angle = set_angle
    assert feed_command(app)["result"]["angle"] == 90
    assert observed == [10, 90] and servo.position == 90


def test_feed_rejects_equal_open_and_closed_angles(farm):
    app, _ = farm
    app.config["feed_open_angle"] = 90
    assert feed_command(app)["error"]["code"] == "bad_args"
    assert app.feed_count == 0
