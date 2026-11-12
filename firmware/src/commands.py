"""Handlers return data only; dispatch sends the response before deferred reboot."""
import gc
from core import protocol as p
from core import wifi

REGISTRY = {}


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
                   "rssi": wlan.status("rssi"), "ip": wlan.ifconfig()[0]})
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


def _actuator(ctx, args):
    name = args.get("name")
    if "name" in args and (not isinstance(name, str) or not name):
        raise CommandError(p.ERR_BAD_ARGS, "name must be a nonempty string")
    actuator = ctx.actuator(name)
    if actuator is None:
        raise CommandError(p.ERR_ACTUATOR_NOT_FOUND,
                           "no actuator '" + str(name) + "'" if name else "name required")
    return actuator


@register("servo_set")
def servo_set(ctx, args):
    _args(args, ("name", "angle"))
    servo = _actuator(ctx, args)
    try:
        servo.set_angle(args.get("angle"))
    except ValueError as exc:
        raise CommandError(p.ERR_BAD_ARGS, str(exc))
    return servo.state()


@register("servo_sequence")
def servo_sequence(ctx, args):
    _args(args, ("name", "run", "angles", "step_ms"))
    servo = _actuator(ctx, args)
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
    except CommandError as exc:
        response.update({"ok": False, "error": {"code": exc.code, "message": str(exc)}})
    except Exception as exc:
        response.update({"ok": False, "error": {"code": p.ERR_INTERNAL, "message": str(exc)}})
    # Only QoS 0 here: a QoS 1 publish inside umqtt's callback waits for PUBACK via wait_msg(),
    # which can re-enter dispatch. Meta (QoS 1) and reboot are handled by the session loop.
    try:
        ctx.publish(p.RESP, response)
    except Exception:
        ctx.reboot_requested = False
        raise
