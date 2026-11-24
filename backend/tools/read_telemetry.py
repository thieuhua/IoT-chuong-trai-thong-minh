"""Print live sensor readings from Mosquitto as JSON lines."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from getpass import getpass
import json
import os
import sys
from uuid import uuid4

import paho.mqtt.client as mqtt

from iot_core import protocol


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", help="Device ID. Defaults to all devices.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--username", default="backend")
    args = parser.parse_args()
    if args.device is not None and not protocol.is_valid_device_id(args.device):
        parser.error("invalid device ID")
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")

    topic_filter = protocol.device_topic(args.device or "+", protocol.TELEMETRY)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"telemetry-{uuid4().hex}")
    exit_code = 0

    def fail(message):
        nonlocal exit_code
        print(message, file=sys.stderr)
        exit_code = 1
        client.disconnect()

    def on_connect(client, _userdata, _flags, reason, _properties):
        if reason.is_failure:
            fail(f"MQTT connection rejected: {reason}")
            return
        result, _mid = client.subscribe(topic_filter)
        if result != mqtt.MQTT_ERR_SUCCESS:
            fail(f"MQTT subscribe failed: {mqtt.error_string(result)}")

    def on_subscribe(_client, _userdata, _mid, reasons, _properties):
        if any(reason.is_failure for reason in reasons):
            fail(f"Broker rejected subscription to {topic_filter}: {reasons}")
        else:
            print(f"Listening on {topic_filter} (Ctrl+C to stop)", file=sys.stderr)

    def on_message(_client, _userdata, message):
        topic = protocol.parse_topic(message.topic)
        if topic is None or topic.kind != protocol.TELEMETRY:
            return
        try:
            envelope = protocol.Envelope.decode(message.payload, protocol.TELEMETRY)
        except protocol.ProtocolError as exc:
            print(f"Invalid telemetry on {message.topic}: {exc}", file=sys.stderr)
            return
        record = {
            "received_at": datetime.now(timezone.utc).isoformat(),
            "device_id": topic.key,
            "device_ts": envelope.ts,
            "data": envelope.data,
        }
        print(json.dumps(record), flush=True)

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    try:
        password = os.environ.get("MQTT_BACKEND_PASSWORD") or getpass("MQTT password: ")
        client.username_pw_set(args.username, password)
        client.connect(args.host, args.port)
        result = client.loop_forever()
        if not exit_code and result != mqtt.MQTT_ERR_SUCCESS:
            print(f"MQTT loop stopped: {mqtt.error_string(result)}", file=sys.stderr)
            return 1
    except (OSError, EOFError) as exc:
        print(f"Unable to read MQTT telemetry: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        client.disconnect()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
