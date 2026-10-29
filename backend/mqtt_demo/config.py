"""Shared defaults; command-line arguments can override host and port."""

import uuid

import paho.mqtt.client as mqtt

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
SUBSCRIBE_TOPIC = "devices/+/data"
SELF_TEST_TOPIC = "devices/backend-demo/data"
PUBLISH_TOPIC = "devices/pc-demo/data"
TIMEOUT_SECONDS = 10


def add_broker_arguments(parser):
    parser.add_argument("--host", default=BROKER_HOST, help="Broker hostname or IP")
    parser.add_argument("--port", type=int, default=BROKER_PORT)


def new_client(role):
    # Unique IDs let several terminals run at the same time.
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"{role}-{uuid.uuid4().hex[:8]}",
        protocol=mqtt.MQTTv311,
    )
    client.connect_timeout = TIMEOUT_SECONDS
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    return client
