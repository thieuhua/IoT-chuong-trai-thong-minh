import time

import machine
import pytest

from actuators import build_actuators
from actuators.servo import Servo
from app import App
from core import protocol as p
from test_commands import invoke


ANGLES = list(range(0, 181, 20))


def config(name="gate", **extra):
    return dict(driver="servo", name=name, pin=26, **extra)


def sequence(**extra):
    return dict(angles=ANGLES[:], step_ms=1000, **extra)


def duty(angle, min_us=500, max_us=2400):
    return (min_us + (max_us - min_us) * angle // 180) * 65535 // 20000


def tick_at(servo, elapsed, now):
    elapsed[0] = now
    servo.tick(time.ticks_ms())


@pytest.mark.parametrize("configs", [
    [dict(driver="missing", name="gate", pin=26)],
    [config(), config()],
    [config(name="")],
    [config(name=None)],
    [dict(driver="servo", pin=26)],
])
def test_build_rejects_invalid_configs(configs):
    with pytest.raises(ValueError):
        build_actuators(configs)


def test_build_actuators():
    assert build_actuators([]) == []
    servos = build_actuators([config(), config(name="other")])
    assert [servo.name for servo in servos] == ["gate", "other"]
    assert all(isinstance(servo, Servo) for servo in servos)


@pytest.mark.parametrize("angle,pulse_us", [(0, 500), (180, 2400), (90, 1450)])
def test_pulse_mapping(angle, pulse_us):
    servo = Servo(config(initial=angle))
    assert servo.pwm.pin.pin == 26
    assert servo.pwm.freq == 50
    assert servo.pwm.duty_values == [0, pulse_us * 65535 // 20000]
    assert servo.angle == angle


@pytest.mark.parametrize("angle,pulse_us", [(0, 1000), (90, 1500), (180, 2000)])
def test_custom_pulse_mapping(angle, pulse_us):
    servo = Servo(config(min_us=1000, max_us=2000, initial=angle))
    assert servo.pwm.duty_values == [0, pulse_us * 65535 // 20000]


def test_sequence_timing_and_ten_second_cycle(board_environment):
    servo = Servo(config(sequence=sequence()))
    assert servo.running and servo.angle is None
    assert servo.pwm.duty_values == [0]
    for index, angle in enumerate(ANGLES + [0]):
        tick_at(servo, board_environment, index * 1000)
        expected = [0] + [duty(value) for value in (ANGLES + [0])[:index + 1]]
        assert servo.pwm.duty_values == expected
        assert servo.angle == angle
        for offset in (1, 20, 999):
            tick_at(servo, board_environment, index * 1000 + offset)
            assert servo.pwm.duty_values == expected
    assert servo.running


def test_sequence_ticks_wraparound(board_environment):
    origin = (1 << 30) - 500
    board_environment[0] = origin
    servo = Servo(config(sequence=sequence()))
    tick_at(servo, board_environment, origin)
    tick_at(servo, board_environment, origin + 999)
    assert servo.pwm.duty_values == [0, duty(0)]
    tick_at(servo, board_environment, origin + 1000)
    assert servo.pwm.duty_values == [0, duty(0), duty(20)]
    tick_at(servo, board_environment, origin + 2000)
    assert servo.pwm.duty_values == [0, duty(0), duty(20), duty(40)]


def test_sequence_resyncs_without_replaying_missed_steps(board_environment):
    servo = Servo(config(sequence=sequence()))
    tick_at(servo, board_environment, 0)
    tick_at(servo, board_environment, 5500)
    assert servo.pwm.duty_values == [0, duty(0), duty(20)]
    for now in (5500, 5501, 6000, 6499):
        tick_at(servo, board_environment, now)
        assert len(servo.pwm.duty_values) == 3
    tick_at(servo, board_environment, 6500)
    assert servo.pwm.duty_values == [0, duty(0), duty(20), duty(40)]


@pytest.mark.parametrize("initial", [None, 35])
def test_autostart_false_uses_initial_angle(initial, board_environment):
    cfg = config(sequence=sequence(autostart=False))
    if initial is not None:
        cfg["initial"] = initial
    servo = Servo(cfg)
    angle = 90 if initial is None else initial
    assert servo.state() == dict(angle=angle, running=False, angles=ANGLES, step_ms=1000)
    tick_at(servo, board_environment, 5000)
    assert servo.pwm.duty_values == [0, duty(angle)]


def test_set_angle_stop_start_and_deinit(board_environment):
    servo = Servo(config(sequence=sequence()))
    tick_at(servo, board_environment, 0)
    servo.set_angle(75)
    assert servo.angle == 75 and not servo.running
    tick_at(servo, board_environment, 1000)
    assert servo.pwm.duty_values == [0, duty(0), duty(75)]
    servo.start()
    assert servo.running
    tick_at(servo, board_environment, 1000)
    assert servo.angle == 0
    servo.stop()
    writes = servo.pwm.duty_values[:]
    tick_at(servo, board_environment, 2000)
    assert servo.pwm.duty_values == writes
    servo.start()
    tick_at(servo, board_environment, 2000)
    assert servo.pwm.duty_values == writes + [duty(0)]
    servo.deinit()
    assert not servo.running and servo.pwm.deinitialized
    tick_at(servo, board_environment, 3000)
    assert servo.pwm.duty_values == writes + [duty(0)]


@pytest.mark.parametrize("angle", [None, True, 1.5, "90", -1, 181])
def test_invalid_angles(angle):
    with pytest.raises(ValueError):
        Servo(config(initial=angle))
    servo = Servo(config())
    with pytest.raises(ValueError):
        servo.set_angle(angle)
    with pytest.raises(ValueError):
        servo.start(angles=[angle])
    with pytest.raises(ValueError):
        Servo(config(sequence=dict(angles=[angle])))


@pytest.mark.parametrize("angles", [[], (), (0, 90), "0,90", 90, None, {}])
def test_invalid_angle_lists(angles):
    with pytest.raises(ValueError):
        Servo(config(sequence=dict(angles=angles)))
    if angles is not None:  # None means retain the configured list in start().
        with pytest.raises(ValueError):
            Servo(config()).start(angles=angles)


@pytest.mark.parametrize("step_ms", [99, 60001, -1, 0, True, 100.5, "100", None])
def test_invalid_step_ms(step_ms):
    with pytest.raises(ValueError):
        Servo(config(sequence=dict(angles=[0], step_ms=step_ms)))
    if step_ms is not None:  # None means retain the configured interval in start().
        with pytest.raises(ValueError):
            Servo(config()).start(angles=[0], step_ms=step_ms)


@pytest.mark.parametrize("step_ms", [100, 60000])
def test_step_ms_bounds(step_ms):
    servo = Servo(config(sequence=dict(angles=[0], step_ms=step_ms)))
    assert servo.running and servo.step_ms == step_ms


def test_start_requires_sequence():
    with pytest.raises(ValueError):
        Servo(config()).start()


@pytest.fixture
def actuator_app(ctx):
    cfg = dict(ctx.config, actuators=[config(sequence=sequence())])
    instance = App(cfg, ctx.identity)
    instance.link = ctx.link
    yield instance
    instance._timer.deinit()
    for servo in instance.actuators:
        servo.deinit()


def test_app_timer_and_lookup(actuator_app, board_environment):
    ctx = actuator_app
    timer = ctx._timer
    servo = ctx.actuator(None)
    assert servo is ctx.actuators[0] is ctx.actuator("gate")
    assert ctx.actuator("missing") is None
    assert timer.id == 0 and timer.mode == machine.Timer.PERIODIC
    assert timer.period == 20 and timer.active
    timer.fire()
    assert servo.pwm.duty_values == [0, duty(0)]
    board_environment[0] = 999
    timer.fire()
    assert servo.pwm.duty_values == [0, duty(0)]
    board_environment[0] = 1000
    timer.fire()
    assert servo.pwm.duty_values == [0, duty(0), duty(20)]
    timer.deinit()
    board_environment[0] = 2000
    timer.fire()
    assert servo.pwm.duty_values == [0, duty(0), duty(20)]


def test_app_tick_failure_isolated(actuator_app, monkeypatch, capsys):
    ctx = actuator_app
    broken = ctx.actuators[0]
    healthy = Servo(config(name="healthy", sequence=sequence()))
    ctx.actuators.append(healthy)

    def fail(now):
        raise OSError("PWM failed")

    monkeypatch.setattr(broken, "tick", fail)
    ctx._timer.fire()
    assert not broken.running
    assert healthy.running and healthy.pwm.duty_values == [0, duty(0)]
    assert "PWM failed" in capsys.readouterr().out
    assert ctx.actuator(None) is None
    assert ctx.actuator("healthy") is healthy


def test_app_meta_actuators_only_when_present(ctx, actuator_app):
    assert "actuators" not in ctx.meta()
    assert ctx._timer is None and ctx.actuator(None) is None
    assert actuator_app.meta()["actuators"] == [
        dict(name="gate", driver="servo", pin=26, range=[0, 180])]


def test_servo_set_command(actuator_app, board_environment):
    ctx = actuator_app
    response = invoke(ctx, "servo_set", dict(name="gate", angle=45))
    assert response == dict(re="cmd-1", ok=True, result=dict(
        angle=45, running=False, angles=ANGLES, step_ms=1000))
    board_environment[0] = 2000
    ctx._timer.fire()
    assert ctx.actuator().pwm.duty_values == [0, duty(45)]
    assert invoke(ctx, "servo_set", dict(angle=90))["result"]["angle"] == 90


def test_servo_sequence_commands(actuator_app, board_environment):
    ctx = actuator_app
    invoke(ctx, "servo_set", dict(angle=45))
    response = invoke(ctx, "servo_sequence", dict(run=True, angles=[10, 80], step_ms=200))
    assert response == dict(re="cmd-1", ok=True, result=dict(
        angle=45, running=True, angles=[10, 80], step_ms=200))
    ctx._timer.fire()
    assert ctx.actuator().angle == 10
    board_environment[0] = 200
    ctx._timer.fire()
    assert ctx.actuator().angle == 80
    response = invoke(ctx, "servo_sequence", dict(name="gate", run=False))
    assert response == dict(re="cmd-1", ok=True, result=dict(
        angle=80, running=False, angles=[10, 80], step_ms=200))
    writes = ctx.actuator().pwm.duty_values[:]
    board_environment[0] = 400
    ctx._timer.fire()
    assert ctx.actuator().pwm.duty_values == writes
    assert invoke(ctx, "servo_sequence")["result"]["running"] is True
    ctx._timer.fire()
    assert ctx.actuator().angle == 10


@pytest.mark.parametrize("name,args", [
    ("servo_set", dict(angle=-1)), ("servo_set", dict(angle=181)),
    ("servo_set", dict(angle=True)), ("servo_set", dict(angle="90")),
    ("servo_set", dict(angle=1.5)), ("servo_set", {}),
    ("servo_set", dict(angle=90, extra=1)),
    ("servo_sequence", dict(run=1)), ("servo_sequence", dict(run="true")),
    ("servo_sequence", dict(run=None)), ("servo_sequence", dict(extra=1)),
    ("servo_sequence", dict(angles=[])), ("servo_sequence", dict(angles="0,90")),
    ("servo_sequence", dict(step_ms=99)), ("servo_sequence", dict(step_ms=60001)),
])
def test_servo_command_bad_args(actuator_app, name, args):
    response = invoke(actuator_app, name, args)
    assert response["ok"] is False
    assert response["error"]["code"] == p.ERR_BAD_ARGS == "bad_args"


@pytest.mark.parametrize("name,args", [
    ("servo_set", dict(angle=90)), ("servo_sequence", dict(run=True)),
])
def test_servo_command_missing_actuator(ctx, actuator_app, name, args):
    for instance, arguments in ((ctx, args), (actuator_app, dict(args, name="missing"))):
        response = invoke(instance, name, arguments)
        assert response["ok"] is False
        assert response["error"]["code"] == p.ERR_ACTUATOR_NOT_FOUND == "actuator_not_found"
