from __future__ import annotations

import json

import pytest

from iot_core import BrokerAuthError
from iot_core.broker_auth import DynSecAuth
from conftest import FakeTransport


async def test_dynsec_timeout_and_unexpected_error():
    transport = FakeTransport()
    auth = DynSecAuth(transport, timeout_s=0.01)
    await auth.start()
    with pytest.raises(BrokerAuthError, match='timed out'):
        await auth.remove_device_account('test-device')
    assert not auth._pending
    async def reject(topic, payload):
        command = json.loads(payload)['commands'][0]
        auth._response(auth.RESPONSE_TOPIC, json.dumps({'responses': [{
            'correlationData': command['correlationData'], 'error': 'Permission denied'}]}).encode())
    transport.on_publish = reject
    with pytest.raises(BrokerAuthError, match='Permission denied'):
        await auth.create_device_account('test-device', 'a' * 32)
    assert not auth._pending
