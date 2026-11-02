from __future__ import annotations

import asyncio
import json

from fastapi import Request
import pytest

from app.main import app, events
from iot_core import (BrokerAuthError, CommandFailed, CommandTimeout, DeviceNotFound,
                      DeviceOffline, InvalidState, RegistrationNotFound)
from test_gateway import request


async def http(gateway, method, path, body=None, query=b''):
    app.state.gateway = gateway
    messages = []
    scope = dict(type='http', asgi={'version': '3.0'}, http_version='1.1', method=method,
                 scheme='http', path=path, raw_path=path.encode(), root_path='', query_string=query,
                 headers=[(b'content-type', b'application/json')], server=('test', 80), client=('test', 1))
    async def receive():
        return {'type': 'http.request', 'body': json.dumps(body).encode() if body is not None else b''}
    async def send(message):
        messages.append(message)
    await app(scope, receive, send)
    status = next(m['status'] for m in messages if m['type'] == 'http.response.start')
    raw = b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body')
    return status, json.loads(raw)


async def test_http_registration_device_and_validation(gateway):
    await request(gateway)
    status, rows = await http(gateway, 'GET', '/registrations')
    assert status == 200 and len(rows) == 1
    assert 'password' not in rows[0] and 'password_hash' not in rows[0]
    status, device = await http(gateway, 'POST', '/registrations/aabbccddeeff/approve', {})
    assert status == 200
    device_id = device['device_id']
    assert (await http(gateway, 'GET', '/health')) == (200, {'broker_connected': True})
    status, renamed = await http(gateway, 'PATCH', f'/devices/{device_id}', {'name': 'Phòng'})
    assert status == 200 and renamed['name'] == 'Phòng'
    assert (await http(gateway, 'GET', f'/devices/{device_id}/telemetry/latest')) == (200, None)
    assert (await http(gateway, 'GET', '/devices', query=b'online=true')) == (200, [])
    assert (await http(gateway, 'PUT', f'/devices/{device_id}/interval', {'seconds': 3601}))[0] == 422
    assert (await http(gateway, 'GET', '/registrations', query=b'status=invalid'))[0] == 422
    assert (await http(gateway, 'DELETE', f'/devices/{device_id}'))[0] == 200
    assert (await http(gateway, 'GET', f'/devices/{device_id}'))[0] == 404


@pytest.mark.parametrize('error,status', [(DeviceNotFound('id'), 404), (RegistrationNotFound('hw'), 404),
    (DeviceOffline('id'), 409), (InvalidState('state'), 409), (CommandTimeout('timeout'), 504),
    (CommandFailed('bad_args', 'bad'), 502), (ValueError('bad value'), 422), (BrokerAuthError('denied'), 502)])
async def test_http_error_mapping(gateway, monkeypatch, error, status):
    async def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(gateway, 'send_command', fail)
    actual, data = await http(gateway, 'POST', '/devices/test-device/commands', {'name': 'ping'})
    assert actual == status
    if isinstance(error, CommandFailed):
        assert data == {'code': 'bad_args', 'message': 'bad'}


async def test_sse_sanitizes_and_unsubscribes(gateway):
    app.state.gateway = gateway
    async def receive():
        await asyncio.Event().wait()
    req = Request({'type': 'http', 'app': app}, receive)
    response = await events(req)
    iterator = response.body_iterator
    task = asyncio.create_task(anext(iterator))
    await asyncio.sleep(0)
    await request(gateway)
    frame = await asyncio.wait_for(task, 1)
    assert frame.startswith('event: registration\ndata: ')
    assert 'password' not in frame
    await iterator.aclose()
    assert all(not callbacks for callbacks in gateway._events.values())
