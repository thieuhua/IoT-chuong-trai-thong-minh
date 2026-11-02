from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib

import pytest

from iot_core import (CommandFailed, CommandTimeout, Device, DeviceNotFound, DeviceOffline,
                      InvalidState, RegistrationNotFound, RegistrationStatus as State)
from iot_core import protocol as p


async def request(gw, hw='aabbccddeeff', password='a' * 32, **updates):
    data = dict(hw_id=hw, password=password, model='esp32', fw='1',
                sensors=[dict(name='room', driver='dht', fields={'temperature': '°C'})], commands=['read'])
    data.update(updates)
    await gw._message(p.provision_request_topic(hw), p.Envelope(p.PROVISION_REQUEST, data).encode())


def last_response(gw):
    return p.Envelope.decode(gw.transport.published[-1][1]).data


async def online_device(gw):
    await request(gw)
    device = await gw.approve('aabbccddeeff', name='Room')
    await gw._message(p.device_topic(device.device_id, p.STATUS), p.Envelope(p.STATUS, {'state': 'online'}).encode())
    return device.device_id


async def test_provision_lost_approval_and_reregistration(gateway):
    events = []
    gateway.on_registration(events.append)
    await request(gateway)
    await request(gateway)
    assert len(events) == 1
    assert last_response(gateway) == {'status': 'pending'}
    await request(gateway, fw='2')
    assert len(events) == 2
    device = await gateway.approve('aabbccddeeff', name='Room')
    registered_at = device.registered_at
    registration = await gateway.registry.get_registration(device.hw_id)
    assert registration.password is None
    assert registration.password_hash == hashlib.sha256(('a' * 32).encode()).hexdigest()
    await request(gateway)
    assert last_response(gateway) == {'status': 'approved', 'device_id': device.device_id}
    assert len(events) == 2
    await request(gateway, password='b' * 32)
    assert last_response(gateway) == {'status': 'pending'}
    assert len(events) == 3
    assert await gateway.get_device(device.device_id)
    new = await gateway.approve(device.hw_id)
    assert new.name == 'Room' and new.registered_at == registered_at
    with pytest.raises(InvalidState):
        await gateway.approve(device.hw_id)


async def test_rejection_revoke_and_new_request(gateway):
    await request(gateway)
    await gateway.reject('aabbccddeeff', 'check board')
    await request(gateway)
    assert last_response(gateway) == {'status': 'rejected', 'reason': 'check board'}
    device = await gateway.approve('aabbccddeeff')
    await gateway.revoke(device.device_id)
    assert gateway.transport.published[-2:] == [
        (p.device_topic(device.device_id, leaf), b'', 1, True) for leaf in (p.STATUS, p.META)]
    assert (await gateway.registry.get_registration(device.hw_id)).status == State.REVOKED
    assert await gateway.telemetry.latest(device.device_id) is None
    with pytest.raises(DeviceNotFound):
        await gateway.get_device(device.device_id)
    await request(gateway)
    assert (await gateway.list_registrations())[0].status == State.PENDING


async def test_approval_validation_and_replacement(gateway):
    with pytest.raises(RegistrationNotFound):
        await gateway.approve('deadbeef')
    await request(gateway)
    for invalid in ('provision', 'A-B', 'x', ''):
        with pytest.raises(ValueError):
            await gateway.approve('aabbccddeeff', device_id=invalid)
    await gateway.approve('aabbccddeeff', device_id='first-device')
    await request(gateway, hw='112233445566')
    with pytest.raises(ValueError):
        await gateway.approve('112233445566', device_id='first-device')
    await request(gateway, password='b' * 32)
    await gateway.approve('aabbccddeeff', device_id='second-device')
    assert await gateway.registry.get_device('first-device') is None
    assert (await gateway.registry.get_registration('aabbccddeeff')).status == State.APPROVED


@pytest.mark.parametrize('data', [{'hw_id': '1234'}, {'password': 'Z' * 32}, {'password': 'a' * 15}, {'password': 123}])
async def test_invalid_provision_ignored(gateway, data):
    await request(gateway, **data)
    assert await gateway.list_registrations(None) == []


async def test_auto_approve(gateway, caplog):
    gateway.config.auto_approve = True
    await request(gateway)
    assert len(await gateway.list_devices()) == 1
    assert last_response(gateway)['status'] == 'approved'
    assert 'development setting' in caplog.text
    await request(gateway, password='b' * 32)
    assert last_response(gateway)['status'] == 'approved'


async def test_status_meta_telemetry_and_events(gateway, caplog):
    statuses, telemetry, updates = [], [], []
    gateway.on_status_change(statuses.append)
    gateway.on_telemetry(telemetry.append)
    gateway.on_device_updated(updates.append)
    device_id = await online_device(gateway)
    status_topic = p.device_topic(device_id, p.STATUS)
    await gateway._message(status_topic, b'')
    await gateway._message(status_topic, p.Envelope(p.STATUS, {'state': 'online'}).encode())
    assert len(statuses) == 1
    await gateway._message(p.device_topic(device_id, p.META), p.Envelope(p.META, {
        'model': 'new', 'fw': '2', 'interval_s': 5, 'sensors': [], 'commands': ['ping']}).encode())
    assert updates[-1].interval_s == 5 and updates[-1].fw == '2'
    await gateway.transport.reconnect()
    assert not (await gateway.get_device(device_id)).online
    assert len(statuses) == 1
    await gateway._message(p.device_topic(device_id, p.TELEMETRY), p.Envelope(p.TELEMETRY, {
        'readings': {'room': {'temperature': 25}}, 'errors': {'soil': 'timeout'}}, ts=123).encode())
    assert len(statuses) == 2 and telemetry[0].device_ts == 123
    assert telemetry[0].received_at.tzinfo == timezone.utc
    assert (await gateway.latest_telemetry(device_id)).readings.errors == {'soil': 'timeout'}
    assert len(await gateway.telemetry_history(device_id)) == 1
    await gateway._message(status_topic, b'bad-json')
    assert status_topic in caplog.text
    await gateway._message(p.device_topic('unknown-device', p.TELEMETRY), p.Envelope(p.TELEMETRY).encode())
    assert await gateway.telemetry.latest('unknown-device') is None
    await gateway.rename(device_id, 'New Room')
    assert (await gateway.list_devices(online=True))[0].name == 'New Room'


async def test_callback_failures_and_unsubscribe(gateway, caplog):
    seen = []
    def fail(value):
        raise RuntimeError('callback failure')
    async def async_cb(value):
        seen.append(value)
    gateway.on_registration(fail)
    unsubscribe = gateway.on_registration(async_cb)
    await request(gateway)
    assert len(seen) == 1 and 'callback failure' in caplog.text
    unsubscribe()
    unsubscribe()
    await request(gateway, fw='2')
    assert len(seen) == 1


async def test_send_command_success_failure_and_spoof(gateway):
    device_id = await online_device(gateway)
    await gateway.registry.save_device(Device('other-device', '1234', online=True))
    async def respond(topic, payload):
        command = p.Envelope.decode(payload)
        # A known, different device must not be able to resolve this request.
        await gateway._message(p.device_topic('other-device', p.RESP), p.Envelope(p.RESP, {
            're': command.id, 'ok': True, 'result': {'spoof': True}}).encode())
        await gateway._message(p.device_topic(device_id, p.RESP), p.Envelope(p.RESP, {
            're': command.id, 'ok': True, 'result': {'uptime_s': 3}}).encode())
    gateway.transport.on_publish = respond
    assert await gateway.ping(device_id) == {'uptime_s': 3}
    assert gateway._pending == {}
    async def fail(topic, payload):
        command = p.Envelope.decode(payload)
        await gateway._message(p.device_topic(device_id, p.RESP), p.Envelope(p.RESP, {
            're': command.id, 'ok': False, 'error': {'code': 'bad_args', 'message': 'bad'}}).encode())
    gateway.transport.on_publish = fail
    with pytest.raises(CommandFailed) as error:
        await gateway.send_command(device_id, 'bad')
    assert error.value.code == 'bad_args' and error.value.message == 'bad'
    assert gateway._pending == {}


async def test_command_timeout_offline_unknown_cancel_and_stop(gateway):
    with pytest.raises(DeviceNotFound):
        await gateway.ping('unknown')
    await request(gateway)
    device = await gateway.approve('aabbccddeeff')
    with pytest.raises(DeviceOffline):
        await gateway.ping(device.device_id)
    await gateway.registry.touch(device.device_id, datetime.now(timezone.utc), True)
    with pytest.raises(CommandTimeout):
        await gateway.send_command(device.device_id, 'ping', timeout_s=0.01)
    assert gateway._pending == {}
    task = asyncio.create_task(gateway.ping(device.device_id))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert gateway._pending == {}
    task = asyncio.create_task(gateway.ping(device.device_id))
    await asyncio.sleep(0)
    await gateway.stop()
    with pytest.raises(CommandTimeout):
        await task


async def test_read_sensor_and_interval(gateway):
    device_id = await online_device(gateway)
    results = {'readings': {'room': {'temperature': 24}}}
    async def respond(topic, payload):
        command = p.Envelope.decode(payload)
        result = {'interval_s': command.data['args']['seconds']} if command.data['name'] == 'set_interval' else results
        await gateway._message(p.device_topic(device_id, p.RESP), p.Envelope(p.RESP, {
            're': command.id, 'ok': True, 'result': result}).encode())
    gateway.transport.on_publish = respond
    assert await gateway.read_sensor(device_id, 'room') == {'temperature': 24}
    assert (await gateway.read_all(device_id)).values == results['readings']
    with pytest.raises(CommandFailed) as error:
        await gateway.read_sensor(device_id, 'missing')
    assert error.value.code == 'sensor_not_found'
    results['errors'] = {'soil': 'timeout'}
    with pytest.raises(CommandFailed) as error:
        await gateway.read_sensor(device_id, 'soil')
    assert error.value.code == 'sensor_error'
    for seconds in (0, 3601, True, 1.5):
        with pytest.raises(ValueError):
            await gateway.set_interval(device_id, seconds)
    assert await gateway.set_interval(device_id, 3) == 3
    assert (await gateway.get_device(device_id)).interval_s == 3
