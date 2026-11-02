import time
from core import protocol as p
from core import wifi
from core.runtime import pause


def run(ctx):
    hw_id = ctx.identity.hw_id
    credentials = ctx.identity.load_device()
    response_topic = p.provision_response_topic(hw_id)
    outcome = {}

    def receive(topic, payload):
        if topic != response_topic:
            return
        try:
            envelope = p.decode(payload, p.PROVISION_RESPONSE)
        except p.ProtocolError as exc:
            print("Ignoring provision response:", exc)
            return
        data = envelope["data"]
        status = data.get("status")
        if status == "approved" and p.is_valid_device_id(data.get("device_id")):
            outcome.update(data)
        elif status == "pending":
            print("waiting for approval, hw_id=" + hw_id)
        elif status == "rejected":
            outcome.update(data)

    link = ctx.new_link(hw_id, ctx.config["mqtt"].get("bootstrap_user", "bootstrap"),
                        ctx.config["mqtt"]["bootstrap_password"], receive)
    try:
        link.connect()
        link.subscribe(response_topic)
        last_request = None
        rejected_at = None
        while True:
            ctx.feed()
            if not wifi.connected():
                raise OSError("Wi-Fi disconnected")
            now = time.ticks_ms()
            if outcome.get("status") == "approved":
                ctx.identity.approve(outcome["device_id"])
                return
            if outcome.get("status") == "rejected":
                print("Provisioning rejected:", outcome.get("reason", ""))
                rejected_at = now
                outcome.clear()
            waiting = rejected_at is not None and time.ticks_diff(now, rejected_at) < 60000
            if not waiting and (last_request is None or rejected_at is not None or
                    time.ticks_diff(now, last_request) >= ctx.config.get("provision_retry_s", 10) * 1000):
                data = ctx.meta()
                del data["interval_s"]
                data["password"] = credentials["password"]
                link.publish(p.provision_request_topic(hw_id), ctx.encode(p.PROVISION_REQUEST, data))
                last_request = now
                rejected_at = None
            link.poll()
            pause(0.05, ctx.feed)
    finally:
        link.close()
