import base64
from types import SimpleNamespace

import pytest

from iot_core import CommandFailed, ota
from iot_core import protocol as p
from tools.sim_device import SimDevice
from tools import sim_device


@pytest.fixture
def sim(tmp_path):
    return SimDevice('7e5700000001', 'localhost', 1883, None, tmp_path, auth=False)


def answer_command(sim, name):
    sim._registered = True
    sim._boot_at = 0
    sim._on_message(None, None, SimpleNamespace(
        payload=p.Envelope(p.CMD, {'name': name, 'args': {}}, id='cmd').encode(), topic='cmd'))


def test_resume_duplicate_chunks_and_complete_bundle(sim):
    sim.files = {'app.py': b'old', 'same.py': b'same', 'deleted.py': b'old', 'config.json': b'{}'}
    files = {'app.py': b'new app', 'same.py': b'same', 'empty.py': b''}
    args = {'version': 'v2', 'files': ota.manifest(files)}
    begin = sim._ota_command('ota_begin', args)
    assert begin == {'need': ['app.py'], 'written': {'app.py': 0, 'empty.py': 0}}
    chunk = {'path': 'app.py', 'offset': 0, 'data': base64.b64encode(b'new').decode()}
    assert sim._ota_command('ota_chunk', chunk)['written'] == 3
    assert sim._ota_command('ota_chunk', chunk)['written'] == 3
    assert sim._ota_command('ota_begin', args)['written']['app.py'] == 3
    status = sim._ota_command('ota_status', {})
    assert status['receiving']['version'] == 'v2'
    with pytest.raises(CommandFailed):
        sim._ota_command('ota_commit', {})
    sim._ota_command('ota_chunk', {'path': 'app.py', 'offset': 3, 'data': 'IGFwcA=='})
    assert sim._ota_command('ota_commit', {}) == {'version': 'v2', 'reboot': True}
    with pytest.raises(CommandFailed):
        sim._ota_command('ota_begin', args)
    sim._install_update()
    assert sim.fw == 'v2' and sim._meta()['ota'] == 'trial'
    assert sim.files == {**files, 'config.json': b'{}'}
    published = []
    sim._publish = lambda *args, **kwargs: published.append(args)
    sim._finish_trial()
    assert sim._ota_state == 'trial' and not published
    answer_command(sim, 'unknown')
    assert sim._commands_ok == 0
    sim._finish_trial()
    assert sim._ota_state == 'trial'
    answer_command(sim, 'ota_status')
    assert sim._commands_ok == 1
    sim._finish_trial()
    assert sim._meta()['ota'] == 'ok' and published[-1][0] == 'meta'


def test_commands_before_reboot_do_not_qualify_trial(sim):
    sim._publish = lambda *args, **kwargs: None
    answer_command(sim, 'ping')
    assert sim._commands_ok == 1
    sim._ota_pending = ('v2', {'app.py': b'new'}, 'v1', {}, False)
    sim._install_update()
    assert sim._commands_ok == 0
    sim._finish_trial()
    assert sim._ota_state == 'trial'


@pytest.mark.parametrize('command_at,confirmed_at', [(1, 3), (4, 4), (None, None)])
def test_run_requires_both_delay_and_post_reboot_command(sim, monkeypatch, command_at, confirmed_at):
    clock = [0]
    monkeypatch.setattr(sim_device, 'time', SimpleNamespace(monotonic=lambda: clock[0], time=lambda: 0))
    sim.device_id = 'dev'
    sim.confirm_delay_s = 3
    sim._commands_ok = 10  # success before reboot cannot qualify the new trial
    sim._ota_pending = ('v2', {'app.py': b'new'}, 'v1', {}, False)
    published = []
    sim._publish = lambda kind, data, **kw: published.append((clock[0], kind, data.copy()))
    class Client:
        def connect(self, *args, **kwargs):
            sim._on_connect(self, None, None, SimpleNamespace(is_failure=False), None)
        def subscribe(self, *args, **kwargs):
            pass
        def will_set(self, *args, **kwargs):
            pass
        def disconnect(self):
            pass
        def loop(self, **kwargs):
            if not sim._stop.is_set():
                clock[0] += 1
                if clock[0] == command_at:
                    answer_command(sim, 'ota_status')
                if clock[0] == 5:
                    sim._stop.set()
            return sim_device.mqtt.MQTT_ERR_SUCCESS
    monkeypatch.setattr(sim_device.mqtt, 'Client', lambda *args, **kwargs: Client())
    sim._run()
    confirmations = [at for at, kind, data in published if kind == p.META and data['ota'] == 'ok']
    assert confirmations == ([] if confirmed_at is None else [confirmed_at])
    assert sim._ota_state == ('trial' if confirmed_at is None else 'ok')


def test_hash_failure_and_abort(sim):
    sim._ota_command('ota_begin', {'version': 'v2', 'files': ota.manifest({'app.py': b'abc'})})
    sim._ota_command('ota_chunk', {'path': 'app.py', 'offset': 0, 'data': 'eHl6'})
    with pytest.raises(CommandFailed, match='sha256'):
        sim._ota_command('ota_commit', {})
    assert sim._ota_command('ota_abort', {}) == {}
    assert sim._ota_command('ota_status', {})['receiving'] is None


def test_rollback_restores_files_config_and_version(sim):
    original = {'app.py': b'old', 'config.json': b'old config'}
    sim.files = original.copy()
    sim.fail_next_update = True
    files = {'app.py': b'bad', 'config.json': b'bad config'}
    sim._ota_command('ota_begin', {'version': 'bad-v2', 'files': ota.manifest(files)})
    for path, data in files.items():
        sim._ota_command('ota_chunk', {'path': path, 'offset': 0, 'data': base64.b64encode(data).decode()})
    sim._ota_command('ota_commit', {})
    assert sim.fail_next_update is False
    sim._install_update()
    assert sim.fw == 'bad-v2'
    sim._publish = lambda *args, **kwargs: None
    sim._finish_trial()
    assert sim.fw == '0.1.0' and sim.files == original
    assert sim._ota_command('ota_status', {})['rolled_back_from'] == 'bad-v2'
