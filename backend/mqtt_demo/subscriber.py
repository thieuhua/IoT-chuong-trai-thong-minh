"""Receive device data; send a test message after the broker confirms subscription."""

import argparse
import json
import sys
import threading

import paho.mqtt.client as mqtt

from config import SELF_TEST_TOPIC, SUBSCRIBE_TOPIC, TIMEOUT_SECONDS
from config import add_broker_arguments, new_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_broker_arguments(parser)
    parser.add_argument("--no-self-test", action="store_true")
    parser.add_argument("--once", action="store_true", help="Exit after one message")
    parser.add_argument("--timeout", type=float, default=TIMEOUT_SECONDS,
                        help="Seconds to wait for a message in --once mode")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")

    ready = threading.Event()
    received = threading.Event()
    errors = []
    client = new_client("backend-demo")

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            errors.append(f"Connection rejected: {reason_code}")
            ready.set()
            return
        result, _ = client.subscribe(SUBSCRIBE_TOPIC, qos=1)
        if result != mqtt.MQTT_ERR_SUCCESS:
            errors.append(f"Subscribe failed: {result}")
            ready.set()

    def on_subscribe(client, userdata, mid, reason_codes, properties):
        if any(code.is_failure for code in reason_codes):
            errors.append(f"Subscription rejected: {reason_codes}")
        else:
            print(f"READY {args.host}:{args.port} | {SUBSCRIBE_TOPIC}", flush=True)
            if not args.no_self_test:
                payload = json.dumps({"device": "backend-demo", "message": "hello MQTT"})
                client.publish(SELF_TEST_TOPIC, payload, qos=1, retain=False)
        ready.set()

    def on_message(client, userdata, message):
        payload = message.payload.decode("utf-8", errors="replace")
        print(f"RX {message.topic} {payload}", flush=True)
        received.set()

    def on_disconnect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"Disconnected ({reason_code}); reconnecting...", flush=True)

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    try:
        client.connect(args.host, args.port, keepalive=60)
        client.loop_start()
        if not ready.wait(TIMEOUT_SECONDS):
            raise TimeoutError("No subscription acknowledgement from broker")
        if errors:
            raise RuntimeError(errors[0])
        if args.once:
            if not received.wait(args.timeout):
                raise TimeoutError("No message received; start publisher after READY")
        else:
            while True:
                threading.Event().wait(1)
    except KeyboardInterrupt:
        print("Stopped.")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"MQTT error: {exc}", file=sys.stderr)
        return 1
    finally:
        client.disconnect()
        client.loop_stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
