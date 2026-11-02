from __future__ import annotations

import asyncio
from pathlib import Path
import secrets
import socket
import threading
import uuid

import paho.mqtt.client as mqtt
import pytest

from iot_core import DeviceGateway, GatewayConfig, RegistrationStatus
from iot_core import protocol as p
from tools.sim_device import SimDevice

ENV_FILE = Path(__file__).resolve().parents[2] / 'deployment/.env'


async def eventually(predicate, timeout=15):
    async with asyncio.timeout(timeout):
        while True:
            result = await predicate()
            if result:
                return result
            await asyncio.sleep(0.05)


@pytest.fixture
async def real_gateway(tmp_path):
    if not ENV_FILE.is_file():
        pytest.skip('deployment/.env is missing')
    try:
        with socket.create_connection(('127.0.0.1', 1883), timeout=1):
            pass
    except OSError:
        pytest.skip('127.0.0.1:1883 is unreachable')
    config = GatewayConfig.from_env(ENV_FILE)
    config.db_path = tmp_path / 'integration.sqlite'
    config.auto_approve = False
    config.command_timeout_s = 5
    async with DeviceGateway.from_config(config) as gateway:
        yield gateway


@pytest.mark.integration
async def test_real_device_lifecycle_and_acl(real_gateway, tmp_path):
    gw = real_gateway
    hw = '7e57' + uuid.uuid4().hex[:8]
    device_id = p.default_device_id(hw)
    simulator = SimDevice(hw, gw.config.broker_host, gw.config.broker_port,
                          gw.config.bootstrap_password, tmp_path / 'sim', retry_s=0.2, interval_s=1)
    status_events = []
    gw.on_status_change(status_events.append)
    attacker = None
    try:
        simulator.start()
        async def pending():
            rows = await gw.list_registrations()
            return next((r for r in rows if r.hw_id == hw), None)
        registration = await eventually(pending)
        assert registration.status == RegistrationStatus.PENDING
        assert len(registration.password) == 32
        device = await gw.approve(hw)
        assert device.device_id == device_id
        async def online():
            return (await gw.get_device(device_id)).online
        await eventually(online)
        assert (await gw.read_sensor(device_id, 'room'))['temperature'] == 24
        assert await gw.set_interval(device_id, 2) == 2
        assert (await gw.get_device(device_id)).interval_s == 2
        async def has_telemetry():
            return await gw.latest_telemetry(device_id)
        await eventually(has_telemetry)
        await gw.reboot(device_id)
        async def rebooted():
            offline = [i for i, e in enumerate(status_events) if not e.online and e.reason == 'reboot']
            return offline and any(e.online for e in status_events[offline[-1] + 1:])
        await eventually(rebooted)

        # Stop the simulator to use its exact pinned client id for ACL checks.
        await asyncio.to_thread(simulator.stop)
        received = []
        other_topic = p.device_topic('7e57-other-device', p.TELEMETRY)
        own_topic = p.device_topic(device_id, p.TELEMETRY)
        await gw.transport.subscribe(other_topic, lambda topic, payload: received.append((topic, payload)))
        await gw.transport.subscribe(own_topic, lambda topic, payload: received.append((topic, payload)))
        attacker = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=device_id,
                               clean_session=True, protocol=mqtt.MQTTv311)
        attacker.username_pw_set(device_id, simulator.password)
        connected = threading.Event()
        refused = []
        def on_connect(client, userdata, flags, reason, properties):
            refused.append(reason.is_failure)
            connected.set()
        attacker.on_connect = on_connect
        attacker.connect(gw.config.broker_host, gw.config.broker_port)
        attacker.loop_start()
        assert await asyncio.to_thread(connected.wait, 5)
        assert refused == [False]
        marker = secrets.token_hex(8).encode()
        attacker.publish(other_topic, marker, qos=0)
        attacker.publish(own_topic, marker, qos=0)
        async def own_received():
            return (own_topic, marker) in received
        await eventually(own_received)
        await asyncio.sleep(0.3)
        assert (other_topic, marker) not in received
        attacker.disconnect()
        await asyncio.to_thread(attacker.loop_stop)
        attacker = None

        # Exercise the existing-client/password-update path too.
        await gw.broker_auth.create_device_account(device_id, simulator.password)
        simulator.start()
        await eventually(online)
        await gw.revoke(device_id)
        assert await gw.registry.get_device(device_id) is None
        async def refused_login():
            return simulator.login_refusals > 0
        await eventually(refused_login)
        assert simulator.device_id is None
    finally:
        await asyncio.to_thread(simulator.stop)
        if attacker:
            attacker.disconnect()
            await asyncio.to_thread(attacker.loop_stop)
        # Cleanup even if any assertion or approval step failed.
        await gw.broker_auth.remove_device_account(device_id)
        for leaf in (p.STATUS, p.META):
            await gw.transport.publish(p.device_topic(device_id, leaf), b'', qos=1, retain=True)


@pytest.mark.integration
async def test_dynsec_exact_errors_and_idempotency(real_gateway):
    auth = real_gateway.broker_auth
    device_id = '7e57-test-' + uuid.uuid4().hex[:8]
    role = 'dev-' + device_id
    try:
        await auth._checked('createRole', rolename=role)
        assert (await auth._command('createRole', rolename=role))['error'] == 'Role already exists'
        args = dict(rolename=role, acltype='publishClientSend', topic=p.device_topic(device_id, p.STATUS), allow=True, priority=0)
        await auth._checked('addRoleACL', **args)
        assert (await auth._command('addRoleACL', **args))['error'] == 'ACL with this topic already exists'
        await auth.create_device_account(device_id, secrets.token_hex(16))
        assert (await auth._command('createClient', username=device_id))['error'] == 'Client already exists'
        assert (await auth._command('addClientRole', username=device_id, rolename=role))['error'] == 'Internal error'
        await auth.create_device_account(device_id, secrets.token_hex(16))
        await auth.remove_device_account(device_id)
        assert (await auth._command('deleteClient', username=device_id))['error'] == 'Client not found'
        assert (await auth._command('deleteRole', rolename=role))['error'] == 'Role not found'
        await auth.remove_device_account(device_id)
    finally:
        await auth.remove_device_account(device_id)
