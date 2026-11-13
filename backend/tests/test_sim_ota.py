import base64

import pytest

from iot_core import CommandFailed, ota
from tools.sim_device import SimDevice


@pytest.fixture
def sim(tmp_path):
    return SimDevice('7e5700000001', 'localhost', 1883, None, tmp_path, auth=False)


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
    assert sim._meta()['ota'] == 'ok' and published[-1][0] == 'meta'


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
