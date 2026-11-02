from __future__ import annotations

import inspect

import pytest

from iot_core import AuthMode, DeviceGateway, GatewayConfig
from iot_core.broker_auth import NoAuth
from iot_core.registry import SqliteDeviceRegistry
from iot_core.telemetry import SqliteTelemetryStore


class FakeTransport:
    def __init__(self):
        self.connected = False
        self.subscriptions = []
        self.callbacks = []
        self.published = []
        self.on_publish = None

    async def start(self):
        self.connected = True
        await self.reconnect()

    async def reconnect(self):
        for callback in self.callbacks:
            result = callback(True)
            if inspect.isawaitable(result):
                await result

    async def stop(self):
        self.connected = False

    def on_connection_change(self, callback):
        self.callbacks.append(callback)

    async def subscribe(self, topic_filter, handler, qos=1, ordered=True):
        self.subscriptions.append((topic_filter, handler, qos))

    async def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))
        if self.on_publish:
            await self.on_publish(topic, payload)


@pytest.fixture
async def gateway(tmp_path):
    path = tmp_path / 'nested/iot.db'
    gw = DeviceGateway(GatewayConfig(auth_mode=AuthMode.NONE), transport=FakeTransport(),
                       registry=SqliteDeviceRegistry(path), telemetry=SqliteTelemetryStore(path), broker_auth=NoAuth())
    async with gw:
        yield gw
