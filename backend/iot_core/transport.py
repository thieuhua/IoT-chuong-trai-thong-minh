"""paho-mqtt client bridged to asyncio. Nothing outside iot_core should import paho."""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from collections.abc import Awaitable, Callable

import paho.mqtt.client as mqtt

logger = logging.getLogger("iot_core")

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
        self.connect_timeout_s = connect_timeout_s
        self.keepalive = keepalive
        self._loop: asyncio.AbstractEventLoop | None = None

        self.client_id = f"{client_id}-{uuid.uuid4().hex[:6]}"
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                   client_id=self.client_id, protocol=mqtt.MQTTv311)
        if username is not None:
            self._client.username_pw_set(username, password)
        self._client.reconnect_delay_set(1, 10)
        self._subscriptions: list[tuple[str, MessageHandler, int]] = []
        self._callbacks: list[Callable[[bool], None]] = []
        self._publishes: dict[int, asyncio.Future[None]] = {}
        self._subacks: dict[int, asyncio.Future[None]] = {}
        self._connected = False
        self._tasks: set[asyncio.Task] = set()
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.on_publish = self._on_publish
        self._client.on_subscribe = self._on_subscribe

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        self._worker = asyncio.create_task(self._dispatch())
        self._ready = self._loop.create_future()
        try:
            self._client.connect_async(self.host, self.port, self.keepalive)
            self._client.loop_start()
            await asyncio.wait_for(self._ready, self.connect_timeout_s)
        except BaseException:
            await self.stop()
            raise

    async def stop(self) -> None:
        # Stop the dispatcher first so it cannot start new handler work during shutdown.
        if hasattr(self, '_worker'):
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        self._client.disconnect()
        await asyncio.to_thread(self._client.loop_stop)
        self._connected = False
        for future in list(self._publishes.values()) + list(self._subacks.values()):
            if not future.done():
                future.set_exception(ConnectionError("MQTT transport stopped"))
        for task in tuple(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._publishes.clear()
        self._subacks.clear()

    @property
    def connected(self) -> bool:
        return self._connected

    async def subscribe(self, topic_filter: str, handler: MessageHandler, qos: int = 1,
                        ordered: bool = True) -> None:
        """ordered=True: messages run one at a time, in arrival order (gateway state).
        ordered=False: handler runs as soon as the message arrives, even while an ordered handler is
        awaiting; use it for replies that ordered handlers wait on (DynSec responses)."""
        if any(t == topic_filter and h == handler for t, h, _, _ in self._subscriptions):
            return
        self._subscriptions.append((topic_filter, handler, qos, ordered))
        # paho's own flag: our _connected lags behind on_connect, which re-sends stored subscriptions.
        if self._client.is_connected():
            rc, mid = self._client.subscribe(topic_filter, qos)
            if rc != mqtt.MQTT_ERR_SUCCESS:
                self._subscriptions.pop()
                raise ConnectionError(f"Subscribe failed: {rc}")
            future = self._loop.create_future()
            self._subacks[mid] = future
            try:
                await asyncio.wait_for(future, self.connect_timeout_s)
            except BaseException:
                self._subscriptions[:] = [s for s in self._subscriptions
                                          if not (s[0] == topic_filter and s[1] == handler)]
                raise
            finally:
                self._subacks.pop(mid, None)

    async def publish(self, topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> None:
        info = self._client.publish(topic, payload, qos=qos, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(f"Publish failed: {info.rc}")
        future = self._loop.create_future()
        self._publishes[info.mid] = future
        try:
            await asyncio.wait_for(future, self.connect_timeout_s)
        finally:
            self._publishes.pop(info.mid, None)

    def on_connection_change(self, callback: Callable[[bool], None]) -> None:
        self._callbacks.append(callback)

    def _schedule(self, callback, *args):
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(callback, *args)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        # Queue connection callbacks before subscriptions can deliver retained messages.
        self._schedule(self._queue.put_nowait, ('connection', not reason_code.is_failure, str(reason_code)))
        if not reason_code.is_failure:
            for topic, _, qos, _ in tuple(self._subscriptions):
                client.subscribe(topic, qos)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self._schedule(self._queue.put_nowait, ('connection', False, str(reason_code)))

    def _on_message(self, client, userdata, message):
        topic, payload = message.topic, bytes(message.payload)
        matches = [(h, ordered) for t, h, _, ordered in tuple(self._subscriptions)
                   if mqtt.topic_matches_sub(t, topic)]
        for handler, ordered in matches:
            if not ordered:
                self._schedule(self._spawn, handler, topic, payload)
        if any(ordered for _, ordered in matches):
            self._schedule(self._queue.put_nowait, ('message', topic, payload))

    def _spawn(self, handler, topic, payload):
        task = asyncio.ensure_future(self._invoke(handler, topic, payload))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _on_publish(self, client, userdata, mid, reason_code, properties):
        self._schedule(self._complete, self._publishes, mid, None)

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        error = ConnectionError("Subscription rejected") if any(r.is_failure for r in reason_codes) else None
        self._schedule(self._complete, self._subacks, mid, error)

    def _complete(self, pending, mid, error):
        future = pending.get(mid)
        if future is not None and not future.done():
            if error:
                future.set_exception(error)
            else:
                future.set_result(None)

    async def _invoke(self, callback, *args):
        try:
            result = callback(*args)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception("MQTT handler failed")

    async def _dispatch(self):
        while True:
            kind, first, second = await self._queue.get()
            if kind == 'connection':
                self._connected = first
                for callback in tuple(self._callbacks):
                    await self._invoke(callback, first)
                if not self._ready.done():
                    if first:
                        self._ready.set_result(None)
                    else:
                        self._ready.set_exception(ConnectionError(second))
            else:
                # Ordered handlers run inline so status/online/offline changes keep broker order.
                # Anything they wait on (publish acks, DynSec replies) bypasses this queue.
                for topic, handler, _, ordered in tuple(self._subscriptions):
                    if ordered and mqtt.topic_matches_sub(topic, first):
                        await self._invoke(handler, first, second)
