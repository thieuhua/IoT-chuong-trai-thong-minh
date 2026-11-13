import re

import pytest

from tools import ota_push


def test_bundle_rules_and_version(tmp_path):
    for name in ['app.py', 'main.py', 'config.json', 'other.json', 'core/module.py',
                 'core/compiled.mpy', '__pycache__/cached.py', 'core/__pycache__/nested.mpy']:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'test')
    files = ota_push.bundle(tmp_path)
    assert set(files) == {'app.py', 'core/module.py', 'core/compiled.mpy'}
    assert set(ota_push.bundle(tmp_path, True)) == set(files) | {'config.json'}
    version = ota_push.default_version(files)
    assert re.fullmatch(r'\d{8}-\d{6}-[0-9a-f]{8}', version)
    assert ota_push.default_version(dict(reversed(list(files.items()))))[-8:] == version[-8:]
    assert ota_push.default_version({**files, 'app.py': b'changed'})[-8:] != version[-8:]


@pytest.mark.parametrize('state,code', [('succeeded', 0), ('failed', 1)])
def test_cli_poll(tmp_path, monkeypatch, capsys, state, code):
    (tmp_path / 'app.py').write_bytes(b'app')
    calls = []
    responses = iter([{'job_id': 'job'}, {'state': 'running', 'progress': {'stage': 'upload', 'sent': 2, 'total': 4}},
                      {'state': state, 'error': 'rollback', 'progress': {'stage': 'done'}}])
    def request(url, body=None):
        calls.append((url, body))
        return next(responses)
    monkeypatch.setattr(ota_push, 'json_request', request)
    monkeypatch.setattr(ota_push.time, 'sleep', lambda _: None)
    assert ota_push.main(['--device', 'esp32-test', '--src', str(tmp_path), '--no-wait']) == code
    assert calls[0][1]['wait_confirm'] is True
    assert calls[0][1]['files'] == {'app.py': 'YXBw'}
    output = capsys.readouterr()
    assert 'upload: 2/4 bytes (50%)' in output.out
    if code:
        assert 'rollback' in output.err


def test_cli_connection_error(tmp_path, monkeypatch):
    (tmp_path / 'app.py').write_bytes(b'app')
    def fail(*args):
        raise OSError('connection refused')
    monkeypatch.setattr(ota_push, 'json_request', fail)
    assert ota_push.main(['--device', 'test', '--src', str(tmp_path)]) == 2


@pytest.mark.parametrize('stage', ['reboot', 'trial'])
def test_no_wait_leaves_server_watching_at_install(tmp_path, monkeypatch, capsys, stage):
    (tmp_path / 'app.py').write_bytes(b'app')
    calls = []
    responses = iter([
        {'job_id': 'job'},
        {'state': 'running', 'progress': {'stage': 'begin'}},
        {'state': 'running', 'progress': {'stage': 'commit'}},
        {'state': 'running', 'progress': {'stage': stage}},
    ])
    def request(url, body=None):
        calls.append((url, body))
        return next(responses)
    monkeypatch.setattr(ota_push, 'json_request', request)
    monkeypatch.setattr(ota_push.time, 'sleep', lambda _: None)
    assert ota_push.main(['--device', 'test', '--src', str(tmp_path), '--no-wait']) == 0
    assert len(calls) == 4
    assert calls[0][1]['wait_confirm'] is True
    assert 'server keeps watching' in capsys.readouterr().out
