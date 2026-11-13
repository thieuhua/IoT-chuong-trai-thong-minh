import asyncio
import base64
from types import SimpleNamespace

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
        self.listeners = []
        self.auto_reboot = True

    def on_status_change(self, callback):
        self.listeners.append(callback)
        return lambda: self.listeners.remove(callback)

    async def get_device(self, device_id):
        return SimpleNamespace(device_id=device_id, online=True)

    def status_changed(self, device_id='dev', online=False):
        for callback in tuple(self.listeners):
            callback(SimpleNamespace(device_id=device_id, online=online))

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
        if name == 'ota_commit' and self.auto_reboot:
            assert self.listeners, 'must subscribe before commit'
            self.status_changed()
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


async def test_chunk_retry(fast_poll):
    gw = FakeGateway()
    gw.chunk_errors = [CommandTimeout('lost reply')]
    await ota.update(gw, 'dev', {'app.py': b'abc'}, 'v2', wait_confirm=False)
    chunks = [args for name, args in gw.calls if name == 'ota_chunk']
    assert len(chunks) == 2 and chunks[0] == chunks[1]
    assert not any(name == 'ota_abort' for name, _ in gw.calls)


@pytest.mark.parametrize('errors', [[CommandTimeout('lost')] * 3, [CommandFailed('ota_error', 'flash')]])
async def test_abort_on_upload_failure(errors, fast_poll):
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
    assert not gw.listeners


@pytest.mark.parametrize('failures', [1, 3])
async def test_device_offline_retry_and_delay(monkeypatch, failures):
    sleeps = []
    async def sleep(seconds):
        sleeps.append(seconds)
    monkeypatch.setattr(ota.asyncio, 'sleep', sleep)
    gw = FakeGateway()
    gw.chunk_errors = [DeviceOffline('dev') for _ in range(failures)]
    if failures == 3:
        with pytest.raises(DeviceOffline):
            await ota.update(gw, 'dev', {'app.py': b'abc'}, 'v2', wait_confirm=False)
    else:
        await ota.update(gw, 'dev', {'app.py': b'abc'}, 'v2', wait_confirm=False)
    chunks = [args for name, args in gw.calls if name == 'ota_chunk']
    assert len(chunks) == min(failures + 1, 3)
    assert all(args == chunks[0] for args in chunks)
    assert sleeps == [2] * min(failures, 2)
    assert (gw.calls[-1][0] == 'ota_abort') is (failures == 3)


async def test_unknown_need_path_is_ota_error():
    gw = FakeGateway(need=['unknown.py'])
    with pytest.raises(CommandFailed, match='unknown files') as exc:
        await ota.update(gw, 'dev', {'app.py': b'abc'}, 'v2')
    assert exc.value.code == 'ota_error'
    assert [name for name, _ in gw.calls] == ['ota_begin']


@pytest.mark.parametrize('written', [-1, 4, True, 1.5, '2', None, {}, []])
async def test_invalid_begin_written_is_dropped(written):
    gw = FakeGateway(written={'app.py': written, 'unknown.py': 100})
    events = []
    await ota.update(gw, 'dev', {'app.py': b'abc'}, 'v2', wait_confirm=False,
                     on_progress=events.append)
    chunks = [args for name, args in gw.calls if name == 'ota_chunk']
    assert [args['offset'] for args in chunks] == [0]
    assert base64.b64decode(chunks[0]['data']) == b'abc'
    assert events[1]['sent'] == 0
    assert not gw.listeners


@pytest.mark.parametrize('cancel_at', [
    'ota_chunk',
    'ota_commit',
    'ota_status',
])
async def test_cancellation_never_aborts(cancel_at):
    gw = FakeGateway()
    entered = asyncio.Event()
    original = gw.send_command
    async def send(device, name, args=None, timeout_s=None):
        if name == cancel_at:
            entered.set()
            await asyncio.Event().wait()
        return await original(device, name, args, timeout_s)
    gw.send_command = send
    task = asyncio.create_task(ota.update(gw, 'dev', {'app.py': b'app'}, 'v2'))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not any(name == 'ota_abort' for name, _ in gw.calls)
    assert not gw.listeners


async def test_waits_for_matching_offline_before_polling_stale_rollback():
    gw = FakeGateway(statuses=[{'version': 'v1', 'state': 'ok', 'rolled_back_from': 'v2'}])
    gw.auto_reboot = False
    waiting = asyncio.Event()
    async def progress(event):
        if event['stage'] == 'reboot':
            waiting.set()
    task = asyncio.create_task(ota.update(gw, 'dev', {'app.py': b'app'}, 'v2',
                                          on_progress=progress, confirm_timeout_s=1))
    try:
        await asyncio.wait_for(waiting.wait(), 1)
        assert gw.listeners
        gw.status_changed('other', False)
        gw.status_changed('dev', True)
        await asyncio.sleep(0)
        assert not task.done()
        assert not any(name == 'ota_status' for name, _ in gw.calls)
        # Reboot clears the stale rollback marker before returning online.
        gw.statuses = iter([{'version': 'v2', 'state': 'ok'}])
        gw.status_changed()
        gw.status_changed(online=True)
        assert (await asyncio.wait_for(task, 1))['state'] == 'confirmed'
        assert not gw.listeners
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_offline_wait_is_bounded(monkeypatch):
    gw = FakeGateway()
    gw.auto_reboot = False
    timeouts = []
    clock = [0.0]
    monkeypatch.setattr(ota, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    real_wait_for = asyncio.wait_for
    async def wait_for(awaitable, timeout):
        timeouts.append(timeout)
        try:
            return await real_wait_for(awaitable, timeout)
        finally:
            clock[0] = 1.0
    monkeypatch.setattr(ota.asyncio, 'wait_for', wait_for)
    with pytest.raises(CommandTimeout):
        await ota.update(gw, 'dev', {'app.py': b'app'}, 'v2', confirm_timeout_s=0.01)
    assert timeouts == [0.01]
    assert not any(name == 'ota_status' for name, _ in gw.calls)
    assert not gw.listeners
