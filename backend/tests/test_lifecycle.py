from __future__ import annotations

import json

import pytest

from conftest import FakeTransport
from iot_core import DeviceOffline, InvalidState, RegistrationNotFound, RegistrationStatus as State
from iot_core import protocol as p
from iot_core.broker_auth import DynSecAuth
from iot_core.registry import SqliteDeviceRegistry
from iot_core.telemetry import SqliteTelemetryStore
from iot_core import AuthMode, DeviceGateway, GatewayConfig
from iot_core.broker_auth import NoAuth
from test_gateway import last_response, online_device, request

HW = 'aabbccddeeff'


async def telemetry(gw, device_id, **data):
    data.setdefault('readings', {'room': {'temperature': 24}})
    await gw._message(p.device_topic(device_id, p.TELEMETRY), p.Envelope(p.TELEMETRY, data).encode())


async def answer_commands(gw, name='ping'):
    async def respond(topic, payload):
        if topic.endswith('/' + p.CMD):
            envelope = p.Envelope.decode(payload)
            device_id = topic.split('/')[2]
            await gw._message(p.device_topic(device_id, p.RESP),
                              p.Envelope(p.RESP, {'re': envelope.id, 'ok': True, 'result': {}}).encode())
    gw.transport.on_publish = respond


async def test_lifecycle_follows_connection_and_faults(gateway):
    events = []
    gateway.on_lifecycle_change(events.append)
    await request(gateway)
    device = await gateway.approve(HW)
    assert device.lifecycle == 'provisioned'
    device_id = await online_device_again(gateway, device.device_id)
    assert (await gateway.get_device(device_id)).lifecycle == 'active'
    await telemetry(gateway, device_id, errors={'room': 'timeout'})
    assert (await gateway.get_device(device_id)).lifecycle == 'fault'
    assert (events[-1].state, events[-1].reason) == ('fault', 'room')
    await telemetry(gateway, device_id)
    assert (await gateway.get_device(device_id)).lifecycle == 'active'
    await gateway._message(p.device_topic(device_id, p.STATUS), p.Envelope(p.STATUS, {'state': 'offline'}).encode())
    assert (await gateway.get_device(device_id)).lifecycle == 'offline'


async def online_device_again(gw, device_id):
    await gw._message(p.device_topic(device_id, p.STATUS), p.Envelope(p.STATUS, {'state': 'online'}).encode())
    return device_id


async def test_suspend_blocks_data_and_commands_until_resume(gateway):
    device_id = await online_device(gateway)
    await telemetry(gateway, device_id)
    before = await gateway.telemetry.latest(device_id)
    device = await gateway.suspend(device_id, 'unpaid')
    assert device.lifecycle == 'suspended'
    await telemetry(gateway, device_id, readings={'room': {'temperature': 99}})
    assert (await gateway.telemetry.latest(device_id)).received_at == before.received_at
    with pytest.raises(InvalidState, match='suspended'):
        await gateway.ping(device_id)
    await request(gateway, password='b' * 32)
    assert last_response(gateway) == {'status': 'rejected', 'reason': 'unpaid'}
    assert (await gateway.registry.get_registration(HW)).status == State.SUSPENDED

    assert (await gateway.resume(device_id)).lifecycle == 'active'
    await answer_commands(gateway)
    await gateway.ping(device_id)
    await telemetry(gateway, device_id, readings={'room': {'temperature': 25}})
    assert (await gateway.telemetry.latest(device_id)).readings.values['room']['temperature'] == 25


async def test_maintenance_allows_inspection_only(gateway):
    device_id = await online_device(gateway)
    assert (await gateway.set_maintenance(device_id, 'sensor swap')).lifecycle == 'maintenance'
    await answer_commands(gateway)
    await gateway.ping(device_id)
    with pytest.raises(InvalidState, match='maintenance'):
        await gateway.send_command(device_id, 'relay_set', {'on': True})
    await telemetry(gateway, device_id)
    assert await gateway.telemetry.latest(device_id)
    await request(gateway)
    assert last_response(gateway)['status'] == 'approved'
    await request(gateway, password='b' * 32)
    assert last_response(gateway)['status'] == 'rejected'
    assert (await gateway.registry.get_registration(HW)).status == State.MAINTENANCE
    assert (await gateway.resume(device_id)).lifecycle == 'active'


async def test_decommission_keeps_history_and_refuses_hardware(gateway):
    device_id = await online_device(gateway)
    await telemetry(gateway, device_id)
    device = await gateway.decommission(device_id, 'retired')
    assert device.lifecycle == 'decommissioned' and not device.online
    assert (await gateway.get_device(device_id)).lifecycle == 'decommissioned'
    assert await gateway.telemetry.latest(device_id)
    await request(gateway, password='b' * 32)
    assert last_response(gateway) == {'status': 'rejected', 'reason': 'retired'}
    assert await gateway.list_registrations() == []
    await online_device_again(gateway, device_id)
    assert not (await gateway.get_device(device_id)).online
    for action in (gateway.revoke, gateway.suspend, gateway.resume, gateway.decommission):
        with pytest.raises(InvalidState):
            await action(device_id)
    with pytest.raises(InvalidState):
        await gateway.approve(HW)


async def test_recommission_requires_new_approval(gateway):
    device_id = await online_device(gateway)
    with pytest.raises(InvalidState):
        await gateway.recommission(HW)
    with pytest.raises(RegistrationNotFound):
        await gateway.recommission('deadbeef')
    await gateway.decommission(device_id)
    await gateway.recommission(HW)
    await request(gateway, password='b' * 32)
    assert last_response(gateway) == {'status': 'pending'}
    assert (await gateway.approve(HW)).device_id == device_id
    assert (await gateway.get_device(device_id)).lifecycle != 'decommissioned'


async def test_invalid_transitions(gateway):
    device_id = await online_device(gateway)
    with pytest.raises(InvalidState):
        await gateway.resume(device_id)
    await gateway.suspend(device_id)
    with pytest.raises(InvalidState):
        await gateway.set_maintenance(device_id)
    with pytest.raises(InvalidState):
        await gateway.suspend(device_id)


async def test_holds_survive_restart(tmp_path):
    path = tmp_path / 'iot.db'
    def build():
        return DeviceGateway(GatewayConfig(auth_mode=AuthMode.NONE), transport=FakeTransport(),
                             registry=SqliteDeviceRegistry(path), telemetry=SqliteTelemetryStore(path),
                             broker_auth=NoAuth())
    async with build() as gw:
        device_id = await online_device(gw)
        await gw.suspend(device_id)
    async with build() as gw:
        assert (await gw.get_device(device_id)).lifecycle == 'suspended'
        with pytest.raises(InvalidState):
            await gw.ping(device_id)


async def test_hardware_version_and_actuators_come_from_meta(gateway):
    device_id = await online_device(gateway)
    relay = {'name': 'relay', 'driver': 'relay', 'pin': 26}
    await gateway._message(p.device_topic(device_id, p.META),
                           p.Envelope(p.META, {'hw': 'devkit-v1', 'actuators': [relay]}).encode())
    device = await gateway.get_device(device_id)
    assert device.hw == 'devkit-v1' and device.actuators == [relay]


async def test_offline_device_still_reports_offline_error(gateway):
    device_id = await online_device(gateway)
    await gateway._message(p.device_topic(device_id, p.STATUS), p.Envelope(p.STATUS, {'state': 'offline'}).encode())
    with pytest.raises(DeviceOffline):
        await gateway.ping(device_id)


async def test_dynsec_suspend_only_touches_telemetry_acl():
    transport = FakeTransport()
    auth = DynSecAuth(transport, timeout_s=1)
    sent = []
    async def accept(topic, payload):
        command = json.loads(payload)['commands'][0]
        sent.append(command)
        auth._response(auth.RESPONSE_TOPIC, json.dumps({'responses': [
            {'correlationData': command['correlationData']}]}).encode())
    transport.on_publish = accept
    await auth.suspend_device_account('dev-1')
    await auth.resume_device_account('dev-1')
    assert [c['command'] for c in sent] == ['removeRoleACL', 'addRoleACL']
    assert {c['topic'] for c in sent} == {p.device_topic('dev-1', p.TELEMETRY)}
    assert {c['acltype'] for c in sent} == {'publishClientSend'}


async def test_silent_device_goes_offline_without_lwt(gateway):
    """Broker restart replays a stale retained "online"; silence must still mean offline."""
    from datetime import datetime, timedelta, timezone
    events = []
    gateway.on_status_change(events.append)
    await request(gateway)
    device_id = await online_device_again(gateway, (await gateway.approve(HW)).device_id)
    now = datetime.now(timezone.utc)
    assert await gateway.check_liveness(now + timedelta(seconds=60)) == []
    assert (await gateway.get_device(device_id)).online
    assert await gateway.check_liveness(now + timedelta(seconds=120)) == [device_id]
    assert (await gateway.get_device(device_id)).lifecycle == 'offline'
    assert (events[-1].online, events[-1].reason) == (False, 'timeout')
    # The next message brings it back.
    await telemetry(gateway, device_id)
    assert (await gateway.get_device(device_id)).online
