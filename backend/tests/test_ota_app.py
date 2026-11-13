import asyncio
from contextlib import asynccontextmanager
import json

from fastapi import Request
import pytest

from app.main import app, events, lifespan
from app.main import MAX_FINISHED_JOBS
from iot_core import CommandFailed, DeviceGateway
from test_app import http


@pytest.fixture(autouse=True)
async def clean_jobs():
    app.state.firmware_jobs = {}
    app.state.firmware_tasks = set()
    app.state.ota_listeners = set()
    yield
    tasks = list(app.state.firmware_tasks)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize('fail', [False, True])
async def test_job_lifecycle_concurrency_and_sse(gateway, monkeypatch, fail):
    release = asyncio.Event()
    calls = []
    async def update(device, files, version, *, on_progress, wait_confirm):
        calls.append((device, files, version, wait_confirm))
        on_progress({'stage': 'upload', 'sent': 3, 'total': 3})
        await release.wait()
        if fail:
            raise CommandFailed('ota_error', 'rolled back')
        return {'state': 'confirmed'}
    monkeypatch.setattr(gateway, 'update_firmware', update)
    app.state.gateway = gateway
    async def receive():
        await asyncio.Event().wait()
    response = await events(Request({'type': 'http', 'app': app}, receive))
    iterator = response.body_iterator
    frame_task = asyncio.create_task(anext(iterator))
    await asyncio.sleep(0)
    body = {'version': 'v2', 'files': {'app.py': 'YWJj'}}
    status, posted = await http(gateway, 'POST', '/devices/dev/firmware', body)
    assert status == 202
    job_id = posted['job_id']
    frame = await asyncio.wait_for(frame_task, 1)
    assert frame.startswith('event: ota\n')
    assert json.loads(frame.split('data: ')[1]) == {
        'stage': 'upload', 'sent': 3, 'total': 3, 'job_id': job_id, 'device_id': 'dev'}
    status, running = await http(gateway, 'GET', f'/firmware-jobs/{job_id}')
    assert status == 200 and running['state'] == 'running'
    assert running['finished_at'] is None and running['progress']['sent'] == 3
    assert (await http(gateway, 'POST', '/devices/dev/firmware', body))[0] == 409
    assert (await http(gateway, 'POST', '/devices/other/firmware', body))[0] == 202
    release.set()
    await asyncio.gather(*app.state.firmware_tasks)
    status, done = await http(gateway, 'GET', f'/firmware-jobs/{job_id}')
    assert done['state'] == ('failed' if fail else 'succeeded')
    assert done['finished_at'] >= done['started_at']
    assert done['version'] == 'v2' and done['device_id'] == 'dev'
    if fail:
        assert 'rolled back' in done['error'] and done['result'] is None
    else:
        assert done['result'] == {'state': 'confirmed'} and done['error'] is None
    assert calls[0] == ('dev', {'app.py': b'abc'}, 'v2', True)
    assert (await http(gateway, 'POST', '/devices/dev/firmware', {**body, 'wait_confirm': False}))[0] == 202
    await asyncio.gather(*app.state.firmware_tasks)
    assert calls[-1][-1] is False
    await iterator.aclose()
    assert not app.state.ota_listeners


@pytest.mark.parametrize('files', [{}, {'app.py': '!invalid!'}, {'app.py': 'é'}, {'app.py': 'YWJj\n'}])
async def test_invalid_files(gateway, files):
    assert (await http(gateway, 'POST', '/devices/dev/firmware', {'version': 'v', 'files': files}))[0] == 422
    assert not app.state.firmware_jobs


async def test_unknown_job(gateway):
    assert (await http(gateway, 'GET', '/firmware-jobs/missing'))[0] == 404


async def test_shutdown_cancels_before_gateway_stop(gateway, monkeypatch):
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    async def update(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    monkeypatch.setattr(gateway, 'update_firmware', update)
    @asynccontextmanager
    async def fake_context():
        yield gateway
        assert cancelled.is_set()
    monkeypatch.setattr(DeviceGateway, 'from_config', lambda _: fake_context())
    monkeypatch.setattr('app.main.GatewayConfig.from_env', lambda _: None)
    async with lifespan(app):
        _, posted = await http(gateway, 'POST', '/devices/dev/firmware',
                               {'version': 'v', 'files': {'app.py': 'YWJj'}})
        await entered.wait()
    job = app.state.firmware_jobs[posted['job_id']]
    assert job['state'] == 'failed' and job['finished_at']
    assert 'cancelled' in job['error']


async def test_job_eviction_removes_oldest_finished_and_keeps_running(gateway, monkeypatch):
    async def update(*args, **kwargs):
        return {'state': 'confirmed'}
    monkeypatch.setattr(gateway, 'update_firmware', update)
    app.state.firmware_jobs = {
        'running': {'device_id': 'busy', 'state': 'running'},
        **{str(i): {'device_id': 'old', 'state': 'succeeded' if i % 2 else 'failed'}
           for i in range(MAX_FINISHED_JOBS + 2)},
    }
    status, posted = await http(gateway, 'POST', '/devices/dev/firmware',
                                {'version': 'v2', 'files': {'app.py': 'YWJj'}})
    assert status == 202
    await asyncio.gather(*app.state.firmware_tasks)
    assert list(app.state.firmware_jobs) == [
        'running', *map(str, range(3, MAX_FINISHED_JOBS + 2)), posted['job_id']]
    assert sum(j['state'] != 'running' for j in app.state.firmware_jobs.values()) == MAX_FINISHED_JOBS


async def test_finished_job_count_never_exceeds_cap(gateway, monkeypatch):
    async def update(*args, **kwargs):
        return {'state': 'confirmed'}
    monkeypatch.setattr(gateway, 'update_firmware', update)
    app.state.firmware_jobs = {
        str(i): {'device_id': 'old', 'state': 'succeeded'} for i in range(MAX_FINISHED_JOBS)}
    status, _ = await http(gateway, 'POST', '/devices/dev/firmware',
                           {'version': 'v2', 'files': {'app.py': 'YWJj'}})
    assert status == 202
    await asyncio.gather(*app.state.firmware_tasks)
    assert sum(j['state'] != 'running' for j in app.state.firmware_jobs.values()) <= MAX_FINISHED_JOBS
