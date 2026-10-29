"""Publish one simulated temperature JSON (or a custom text message), then exit."""

import argparse
from datetime import datetime, timezone
import json
import sys
import threading

from config import PUBLISH_TOPIC, TIMEOUT_SECONDS, add_broker_arguments, new_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_broker_arguments(parser)
    parser.add_argument("--topic", default=PUBLISH_TOPIC)
    parser.add_argument("--temperature", type=float, default=27.5)
    parser.add_argument("--message", help="Send plain text instead of temperature JSON")
    args = parser.parse_args()
    connected = threading.Event()
    errors = []
    client = new_client("publisher-demo")

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            errors.append(f"Connection rejected: {reason_code}")
        connected.set()

    client.on_connect = on_connect
    try:
        payload = args.message if args.message is not None else json.dumps({
            "device": "pc-demo",
            "temperature_c": args.temperature,
            "simulated": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, allow_nan=False)
        client.connect(args.host, args.port, keepalive=60)
        client.loop_start()
        if not connected.wait(TIMEOUT_SECONDS):
            raise TimeoutError("No connection acknowledgement from broker")
        if errors:
            raise RuntimeError(errors[0])
        message = client.publish(args.topic, payload, qos=1, retain=False)
        message.wait_for_publish(timeout=TIMEOUT_SECONDS)
        if not message.is_published():
            raise TimeoutError("Broker did not acknowledge the publish")
        print(f"TX {args.topic} {payload}")
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"MQTT error: {exc}", file=sys.stderr)
        return 1
    finally:
        client.disconnect()
        client.loop_stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
