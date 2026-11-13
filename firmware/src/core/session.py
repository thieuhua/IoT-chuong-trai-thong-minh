import gc
import machine
import time
import commands
from core import ota
from core import protocol as p
from core import wifi
from core.mqtt_link import NotAuthorised
from core.runtime import pause

AUTH_FAILURES_BEFORE_REVOKE = 3
OTA_CONFIRM_AFTER_MS = 30000


def run(ctx):
    credentials = ctx.identity.device
    device_id = credentials["device_id"]
    command_topic = p.device_topic(device_id, p.CMD)

    def receive(topic, payload):
        if topic == command_topic:
            commands.dispatch(ctx, payload)

    link = ctx.new_link(device_id, device_id, credentials["password"], receive)
    ctx.link = link
    graceful = False
    try:
        link.set_last_will(p.device_topic(device_id, p.STATUS),
                           ctx.encode(p.STATUS, {"state": "offline", "reason": "lwt"}))
        try:
            link.connect()
        except NotAuthorised:
            # One refusal can be a broker hiccup; only forget the identity after repeated ones.
            ctx.auth_failures += 1
            if ctx.auth_failures < AUTH_FAILURES_BEFORE_REVOKE:
                raise
            ctx.auth_failures = 0
            ctx.identity.revoke()
            return
        ctx.auth_failures = 0
        # Subscribe before announcing online: the backend may send a command as soon as it sees it.
        link.subscribe(command_topic)
        ctx.publish(p.STATUS, {"state": "online"}, retain=True, qos=1)
        ctx.publish_meta()
        ctx.backoff_s = 2
        gc.collect()
        last_telemetry = time.ticks_ms()
        last_gc = last_telemetry
        online_since = last_telemetry
        trial = ota.in_trial()
        while True:
            ctx.feed()
            if not wifi.connected():
                raise OSError("Wi-Fi disconnected")
            link.poll()
            if ctx.meta_dirty:
                ctx.meta_dirty = False
                ctx.publish_meta()
            if ctx.reboot_requested:
                ctx.publish(p.STATUS, {"state": "offline", "reason": "reboot"}, retain=True, qos=1)
                link.close()
                pause(1, ctx.feed)
                machine.reset()
                return
            now = time.ticks_ms()
            if time.ticks_diff(now, last_telemetry) >= ctx.interval_s * 1000:
                ctx.publish(p.TELEMETRY, ctx.read_sensors())
                last_telemetry = now
            if (trial and ctx.commands_ok
                    and time.ticks_diff(now, online_since) >= OTA_CONFIRM_AFTER_MS):
                # New OTA version stayed online and answered a command (so it can still be
                # updated remotely): keep it. The backend polls ota_status during the trial.
                trial = False
                if ota.confirm():
                    print("OTA: version", ctx.fw_version(), "confirmed")
                    ctx.meta_dirty = True
            if time.ticks_diff(now, last_gc) >= 30000:
                gc.collect()
                last_gc = now
            pause(0.05, ctx.feed)
    except KeyboardInterrupt:
        try:
            ctx.publish(p.STATUS, {"state": "offline", "reason": "shutdown"}, retain=True, qos=1)
            graceful = True
        except OSError:
            pass
        raise
    finally:
        link.close(graceful=graceful)
        ctx.link = None
