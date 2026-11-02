"""paho-mqtt client bridged to asyncio. Nothing outside iot_core should import paho."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

# handler(topic, payload) runs on the asyncio loop thread, never on paho's thread.
MessageHandler = Callable[[str, bytes], "Awaitable[None] | None"]


class MqttTransport:
    """Thin async wrapper around paho.mqtt.client (CallbackAPIVersion.VERSION2, MQTT 3.1.1).

    Contract:
    - `start()` connects, starts paho's network thread and waits for CONNACK (raise on failure/timeout).
    - Subscriptions registered with `subscribe()` are re-sent in on_connect, so they survive reconnects.
    - Every paho callback hands work to the asyncio loop with loop.call_soon_threadsafe; handlers
      (sync or async) run on the loop. A handler exception is logged, never kills the client.
    - `publish()` is awaitable and resolves when paho reports the message sent (QoS 0) or acknowledged (QoS 1).
    - `on_connection_change(cb)` reports connected True/False to the gateway.
    """

    def __init__(self, host: str, port: int, *, username: str | None = None,
                 password: str | None = None, client_id: str = "backend",
                 connect_timeout_s: float = 10.0, keepalive: int = 30):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.client_id = client_id
        self.connect_timeout_s = connect_timeout_s
        self.keepalive = keepalive
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    @property
    def connected(self) -> bool: ...

    async def subscribe(self, topic_filter: str, handler: MessageHandler, qos: int = 1) -> None: ...

    async def publish(self, topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> None: ...

    def on_connection_change(self, callback: Callable[[bool], None]) -> None: ...

