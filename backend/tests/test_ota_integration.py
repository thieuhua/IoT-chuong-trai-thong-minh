import asyncio
import uuid

import pytest

from iot_core import AuthMode, CommandFailed, ota
from iot_core import protocol as p
from test_integration import eventually, real_gateway
from tools.sim_device import SimDevice


@pytest.mark.integration
async def test_real_ota_confirm_and_rollback(real_gateway, tmp_path):
    gw = real_gateway
    hw = '7e57' + uuid.uuid4().hex[:8]
    device_id = p.default_device_id(hw)
    simulator = SimDevice(hw, gw.config.broker_host, gw.config.broker_port,
                          gw.config.bootstrap_password, tmp_path / 'sim', retry_s=0.1,
                          auth=gw.config.auth_mode == AuthMode.DYNSEC,
                          confirm_delay_s=0.15, reboot_delay_s=0.1)
    meta = []
    async def observe_meta(topic, payload):
        if payload:
            data = p.Envelope.decode(payload).data
            meta.append((data['fw'], data.get('ota')))
    await gw.transport.subscribe(p.device_topic(device_id, p.META), observe_meta)
    try:
        simulator.start()
        async def pending():
            return next((r for r in await gw.list_registrations() if r.hw_id == hw), None)
        await eventually(pending)
        await gw.approve(hw)
        async def online():
            return (await gw.get_device(device_id)).online
        await eventually(online)
        files = {'app.py': b'# new app\n' * 600, 'core/new.py': b'# new module'}
        result = await ota.update(gw, device_id, files, 'test-v2', confirm_timeout_s=15)
        assert result['state'] == 'confirmed' and simulator.files == files
        assert ('test-v2', 'trial') in meta and ('test-v2', 'ok') in meta
        simulator.fail_next_update = True
        with pytest.raises(CommandFailed) as exc:
            await ota.update(gw, device_id, {'app.py': b'# broken'}, 'test-bad', confirm_timeout_s=15)
        assert exc.value.code == 'ota_error'
        status = await gw.send_command(device_id, 'ota_status')
        assert status['rolled_back_from'] == 'test-bad'
        assert status['version'] == 'test-v2' and status['state'] == 'ok'
        assert simulator.files == files
    finally:
        await asyncio.to_thread(simulator.stop)
        await gw.broker_auth.remove_device_account(device_id)
        for leaf in (p.STATUS, p.META):
            await gw.transport.publish(p.device_topic(device_id, leaf), b'', qos=1, retain=True)
