"""Handlers return data only; dispatch sends the response before deferred reboot."""
import gc
import time
from core import protocol as p
from core import wifi
from core.runtime import pause

REGISTRY = {}
FEED_BUDGET_MS = 9500  # backend default command_timeout_s = 10; leave response margin


class CommandError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def register(name):
    def decorator(handler):
        REGISTRY[name] = handler
        return handler
    return decorator


def _args(args, allowed=()):
    if any(key not in allowed for key in args):
        raise CommandError(p.ERR_BAD_ARGS, "unexpected argument")


@register("ping")
def ping(ctx, args):
    _args(args)
    return {"uptime_s": ctx.uptime_s()}


@register("get_info")
def get_info(ctx, args):
    _args(args)
    result = ctx.meta()
    wlan = wifi.interface()
    result.update({"uptime_s": ctx.uptime_s(), "mem_free": gc.mem_free(),
                   "rssi": wlan.status("rssi"), "ip": wlan.ifconfig()[0],
                   "ssid": (ctx.network or {}).get("ssid")})
    from core.mqtt_link import last_error
    error = last_error()
    if error:
        result["last_mqtt_error"] = error
    return result


@register("read")
def read(ctx, args):
    _args(args, ("sensor",))
    name = args.get("sensor")
    if "sensor" in args and (not isinstance(name, str) or not name):
        raise CommandError(p.ERR_BAD_ARGS, "sensor must be a nonempty string")
    if name is not None and not any(sensor.name == name for sensor in ctx.sensors):
        raise CommandError(p.ERR_SENSOR_NOT_FOUND, "no sensor '" + name + "'")
    result = ctx.read_sensors(name)
    if name is not None and result.get("errors"):
        raise CommandError(p.ERR_SENSOR_ERROR, result["errors"][name])
    return result


@register("set_interval")
def set_interval(ctx, args):
    _args(args, ("seconds",))
    seconds = args.get("seconds")
    if type(seconds) is not int or not 1 <= seconds <= 3600:
        raise CommandError(p.ERR_BAD_ARGS, "seconds must be an integer in 1..3600")
    ctx.identity.set_interval(seconds)
    ctx.interval_s = seconds
    ctx.meta_dirty = True
    return {"interval_s": seconds}


def _actuator(ctx, args, driver=None):
    name = args.get("name")
    if "name" in args and (not isinstance(name, str) or not name):
        raise CommandError(p.ERR_BAD_ARGS, "name must be a nonempty string")
    actuator = ctx.actuator(name, driver)
    if actuator is None:
        kind = driver or "actuator"
        raise CommandError(p.ERR_ACTUATOR_NOT_FOUND,
                           "no " + kind + " '" + str(name) + "'" if name else
                           "name required (not exactly one " + kind + ")")
    return actuator


@register("actuator_state")
def actuator_state(ctx, args):
    """Read-only: current state of one actuator, or of all of them by name."""
    _args(args, ("name",))
    if "name" in args:
        return _actuator(ctx, args).state()
    return {actuator.name: actuator.state() for actuator in ctx.actuators}


@register("servo_set")
def servo_set(ctx, args):
    _args(args, ("name", "angle"))
    servo = _actuator(ctx, args, "servo")
    try:
        servo.set_angle(args.get("angle"))
    except ValueError as exc:
        raise CommandError(p.ERR_BAD_ARGS, str(exc))
    return servo.state()


@register("servo_sequence")
def servo_sequence(ctx, args):
    _args(args, ("name", "run", "angles", "step_ms"))
    servo = _actuator(ctx, args, "servo")
    run = args.get("run", True)
    if type(run) is not bool:
        raise CommandError(p.ERR_BAD_ARGS, "run must be true or false")
    try:
        if run:
            servo.start(args.get("angles"), args.get("step_ms"))
        else:
            servo.stop()
    except ValueError as exc:
        raise CommandError(p.ERR_BAD_ARGS, str(exc))
    return servo.state()


@register("relay_set")
def relay_set(ctx, args):
    _args(args, ("name", "on", "duration_ms"))
    relay = _actuator(ctx, args, "relay")
    fan = ctx.fan_control
    if fan is not None and relay is fan.relay:
        ctx.control_tick()
        if fan.fault and args.get("on") is False:
            raise CommandError(p.ERR_SENSOR_ERROR, "fan is forced on after sensor failures")
    try:
        relay.set(args.get("on"), args.get("duration_ms"))
    except ValueError as exc:
        raise CommandError(p.ERR_BAD_ARGS, str(exc))
    if fan is not None and relay is fan.relay:
        fan.manual()
    return relay.state()


@register("mode_set")
def mode_set(ctx, args):
    _args(args, ("mode",))
    mode = args.get("mode")
    if mode not in ("auto", "manual"):
        raise CommandError(p.ERR_BAD_ARGS, "mode must be auto or manual")
    if ctx.fan_control is None:
        raise CommandError(p.ERR_ACTUATOR_NOT_FOUND, "fan controller not configured")
    ctx.control_tick()
    ctx.fan_control.set_mode(mode)
    return ctx.fan_control.status()


def _feed_move(ctx, servo, angle, deadline):
    # Establish a fresh slew clock even on hosts without a running hardware timer.
    servo.tick(time.ticks_ms())
    servo.set_angle(angle)
    while servo.position != angle:
        if time.ticks_diff(time.ticks_ms(), deadline) >= 0:
            raise CommandError(p.ERR_INTERNAL, "servo movement timed out")
        ctx.feed()
        servo.tick(time.ticks_ms())
        time.sleep_ms(20)


@register("feed")
def feed(ctx, args):
    _args(args, ("seconds",))
    seconds = args.get("seconds")
    if type(seconds) is not int or not 1 <= seconds <= 10:
        raise CommandError(p.ERR_BAD_ARGS, "seconds must be an integer in 1..10")
    servo = ctx.actuator(ctx.config.get("feed_servo", "servo"), "servo")
    if servo is None:
        raise CommandError(p.ERR_ACTUATOR_NOT_FOUND, "feed servo not found")
    # Feeder gate: closed at feed_closed_angle (default 90), open at feed_open_angle (default 10).
    angle = ctx.config.get("feed_open_angle", 10)
    closed = ctx.config.get("feed_closed_angle", 90)
    limit = ctx.config.get("feed_limit_per_day", 6)
    if (type(angle) is not int or not 0 <= angle <= 180
            or type(closed) is not int or not 0 <= closed <= 180 or angle == closed
            or type(limit) is not int or limit < 1
            or (servo.max_dps is not None and
                (type(servo.max_dps) not in (int, float)
                 or not p._finite(servo.max_dps) or servo.max_dps < 0))):
        raise CommandError(p.ERR_BAD_ARGS, "invalid feed configuration")
    travel_ms = 0
    if servo.max_dps:
        position = servo.position if servo.position is not None else angle
        travel_ms = (abs(position - angle) + abs(angle - closed)) * 1000 / servo.max_dps
    # Include timer granularity for both moves and cooperative waits. Never shorten
    # requested dispensing time silently, or begin a command that cannot finish in time.
    if seconds * 1000 + travel_ms + 200 >= FEED_BUDGET_MS:
        raise CommandError(p.ERR_BAD_ARGS, "feed duration and servo travel exceed 9.5s budget")
    deadline = time.ticks_add(time.ticks_ms(), FEED_BUDGET_MS)
    ctx.feed()
    if ctx.feed_count >= limit:
        raise CommandError(p.ERR_FEED_LIMIT, "daily feed limit reached")
    # Count an attempt before any motion; partial/failed dispensing still consumes a slot.
    ctx.feed_count += 1
    try:
        _feed_move(ctx, servo, angle, deadline)
        pause(seconds, ctx.feed)
    finally:
        _feed_move(ctx, servo, closed, deadline)
    return {"seconds": seconds, "angle": closed, "feed_count": ctx.feed_count}


def _ota_call(fn):
    from core.ota import OtaError
    try:
        return fn()
    except OtaError as exc:
        raise CommandError(exc.code, str(exc))
    except OSError as exc:
        raise CommandError(p.ERR_OTA, "flash error: " + str(exc))


@register("ota_begin")
def ota_begin(ctx, args):
    _args(args, ("version", "files"))
    from core import ota
    rx = ctx.ota_rx
    if rx is not None and rx.same_manifest(args.get("version"), args.get("files")):
        # Repeated begin (QoS 1 redelivery or backend resume): keep what was already received.
        return {"need": rx.need(), "written": rx.progress()}
    ctx.ota_rx = None
    ctx.ota_rx = _ota_call(lambda: ota.Receiver(args.get("version"), args.get("files")))
    return {"need": ctx.ota_rx.need(), "written": ctx.ota_rx.progress()}


@register("ota_chunk")
def ota_chunk(ctx, args):
    _args(args, ("path", "offset", "data"))
    if ctx.ota_rx is None:
        raise CommandError(p.ERR_OTA, "no update in progress")
    written = _ota_call(lambda: ctx.ota_rx.chunk(args.get("path"), args.get("offset"), args.get("data")))
    return {"path": args.get("path"), "written": written}


@register("ota_commit")
def ota_commit(ctx, args):
    _args(args)
    if ctx.ota_rx is None:
        raise CommandError(p.ERR_OTA, "no update in progress")
    receiver = ctx.ota_rx
    _ota_call(lambda: receiver.commit(ctx.fw_version()))
    ctx.ota_rx = None
    # The loader installs it on the next boot; the session loop answers first, publishes
    # offline, then resets.
    ctx.reboot_requested = True
    return {"version": receiver.version, "reboot": True}


@register("ota_abort")
def ota_abort(ctx, args):
    _args(args)
    from core import ota
    ctx.ota_rx = None
    _ota_call(ota.abort)
    return {}


@register("ota_status")
def ota_status(ctx, args):
    _args(args)
    from core import ota
    state = ota.load_state()
    return {"version": ctx.fw_version(), "state": state.get("state", "ok"),
            "boots": state.get("boots", 0), "rolled_back_from": state.get("rolled_back_from"),
            "receiving": ctx.ota_rx.status() if ctx.ota_rx else None}


@register("reboot")
def reboot(ctx, args):
    _args(args)
    ctx.reboot_requested = True
    return {}


def dispatch(ctx, payload):
    try:
        envelope = p.decode(payload, p.CMD)
    except p.ProtocolError as exc:
        print("Ignoring command:", exc)
        return
    data = envelope["data"]
    is_feed = data.get("name") == "feed"
    if is_feed:
        for command_id, previous in ctx.feed_responses:
            if command_id == envelope["id"]:
                ctx.publish(p.RESP, previous)
                return
    now = ctx.clock.now()
    ttl = data.get("ttl_s")
    valid_ttl = type(ttl) in (int, float) and p._finite(ttl) and ttl >= 0
    if (now is not None and envelope["ts"] is not None and valid_ttl
            and envelope["ts"] + ttl < now):
        return
    response = {"re": envelope["id"]}
    try:
        name, args = data.get("name"), data.get("args", {})
        if not isinstance(name, str) or not isinstance(args, dict):
            raise CommandError(p.ERR_BAD_ARGS, "name must be string and args must be object")
        if "ttl_s" in data and not valid_ttl:
            raise CommandError(p.ERR_BAD_ARGS, "ttl_s must be a nonnegative number")
        handler = REGISTRY.get(name)
        if handler is None:
            raise CommandError(p.ERR_UNKNOWN_COMMAND, "unknown command: " + name)
        result = handler(ctx, args)
        response.update({"ok": True, "result": result})
        # Proof that the whole cmd -> resp path works; an OTA trial only confirms after this.
        ctx.commands_ok = getattr(ctx, "commands_ok", 0) + 1
    except CommandError as exc:
        response.update({"ok": False, "error": {"code": exc.code, "message": str(exc)}})
    except Exception as exc:
        response.update({"ok": False, "error": {"code": p.ERR_INTERNAL, "message": str(exc)}})
    if is_feed:
        # Cache BEFORE publishing: a dropped response must never dispense twice.
        ctx.feed_responses.append((envelope["id"], response))
        if len(ctx.feed_responses) > 8:
            ctx.feed_responses.pop(0)
    # Only QoS 0 here: a QoS 1 publish inside umqtt's callback waits for PUBACK via wait_msg(),
    # which can re-enter dispatch. Meta (QoS 1) and reboot are handled by the session loop.
    try:
        ctx.publish(p.RESP, response)
    except Exception:
        ctx.reboot_requested = False
        raise
