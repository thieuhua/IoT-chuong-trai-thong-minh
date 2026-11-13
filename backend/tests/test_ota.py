import asyncio
import base64

import pytest

from iot_core import CommandFailed, CommandTimeout, DeviceOffline
from iot_core import ota


class FakeGateway:
    def __init__(self, need=None, written=None, statuses=None):
        self.need = need or ['app.py']
        self.written = written or {}
        self.statuses = iter(statuses or [{'version': 'v2', 'state': 'ok'}])
        self.calls = []
        self.chunk_errors = []

    async def send_command(self, device_id, name, args=None, timeout_s=None):
        self.calls.append((name, args))
        if name == 'ota_begin':
            return {'need': self.need, 'written': self.written}
        if name == 'ota_chunk':
            if self.chunk_errors:
                raise self.chunk_errors.pop(0)
            return {'written': args['offset'] + len(base64.b64decode(args['data']))}
        if name == 'ota_status':
            status = next(self.statuses)
            if isinstance(status, Exception):
                raise status
            return status
        return {}


async def test_need_chunk_offsets_and_resume():
    gw = FakeGateway(written={'app.py': 2048})
    data = b'x' * 6500
    progress = []
    result = await ota.update(gw, 'dev', {'app.py': data, 'same.py': b'unchanged'}, 'v2',
                              wait_confirm=False, on_progress=progress.append)
    chunks = [args for name, args in gw.calls if name == 'ota_chunk']
    assert [c['offset'] for c in chunks] == [2048, 4096, 6144]
    assert [len(base64.b64decode(c['data'])) for c in chunks] == [2048, 2048, 356]
    assert {c['path'] for c in chunks} == {'app.py'}
    assert b''.join(base64.b64decode(c['data']) for c in chunks) == data[2048:]
    assert progress[1]['sent'] == 2048
    assert progress[-2]['sent'] == 6500
    assert result['sent_files'] == 1 and result['state'] == 'committed'


async def test_chunk_retry():
    gw = FakeGateway()
    gw.chunk_errors = [CommandTimeout('lost reply')]
    await ota.update(gw, 'dev', {'app.py': b'abc'}, 'v2', wait_confirm=False)
    chunks = [args for name, args in gw.calls if name == 'ota_chunk']
    assert len(chunks) == 2 and chunks[0] == chunks[1]
    assert not any(name == 'ota_abort' for name, _ in gw.calls)


@pytest.mark.parametrize('errors', [[CommandTimeout('lost')] * 3, [CommandFailed('ota_error', 'flash')]])
async def test_abort_on_upload_failure(errors):
    gw = FakeGateway()
    gw.chunk_errors = errors.copy()
    with pytest.raises(type(errors[0])):
        await ota.update(gw, 'dev', {'app.py': b'abc'}, 'v2')
    assert gw.calls[-1][0] == 'ota_abort'
    assert not any(name == 'ota_commit' for name, _ in gw.calls)


@pytest.fixture
def fast_poll(monkeypatch):
    async def sleep(_):
        return None
    monkeypatch.setattr(ota.asyncio, 'sleep', sleep)


async def test_confirm_after_offline_and_trial(fast_poll):
    gw = FakeGateway(statuses=[DeviceOffline('dev'), CommandTimeout('reboot'),
                              {'version': 'v2', 'state': 'trial', 'boots': 1},
                              {'version': 'v2', 'state': 'ok'}])
    events = []
    async def progress(event):
        events.append(event)
    result = await ota.update(gw, 'dev', {'app.py': b'app'}, 'v2', on_progress=progress)
    assert result['state'] == 'confirmed'
    assert [e['stage'] for e in events][-3:] == ['reboot', 'trial', 'done']


async def test_rollback(fast_poll):
    gw = FakeGateway(statuses=[{'version': 'v1', 'state': 'ok', 'rolled_back_from': 'v2'}])
    with pytest.raises(CommandFailed) as exc:
        await ota.update(gw, 'dev', {'app.py': b'app'}, 'v2')
    assert exc.value.code == 'ota_error'


@pytest.mark.parametrize('files', [{}, {'core.py': b'abc'}])
async def test_manifest_validation(files):
    gw = FakeGateway()
    with pytest.raises(ValueError):
        await ota.update(gw, 'dev', files, 'v2')
    assert not gw.calls


async def test_commit_failure_aborts():
    gw = FakeGateway()
    original = gw.send_command
    async def send(device, name, args=None, timeout_s=None):
        if name == 'ota_commit':
            raise CommandFailed('ota_error', 'hash mismatch')
        return await original(device, name, args, timeout_s)
    gw.send_command = send
    with pytest.raises(CommandFailed):
        await ota.update(gw, 'dev', {'app.py': b'app'}, 'v2')
    assert gw.calls[-1][0] == 'ota_abort'
