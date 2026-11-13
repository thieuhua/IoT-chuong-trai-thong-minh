import builtins
import json
from pathlib import Path
from types import SimpleNamespace

import app
import machine
import pytest
from core import ota, session, wifi
from test_commands import invoke
from test_ota import encoded, entry, put, save
from umqtt.simple import MQTTClient


def begin(ctx, version="v2", data=b"new"):
    return invoke(ctx, "ota_begin", {"version": version, "files": [entry(data=data)]})


def chunk(ctx, data=b"new", offset=0):
    return invoke(ctx, "ota_chunk", {"path": "app.py", "offset": offset, "data": encoded(data)})


def test_begin_same_manifest_keeps_receiver_and_progress(ctx):
    assert begin(ctx)["result"] == {"need": ["app.py"], "written": {"app.py": 0}}
    original = ctx.ota_rx
    assert chunk(ctx, b"n")["result"] == {"path": "app.py", "written": 1}
    assert begin(ctx)["result"] == {"need": ["app.py"], "written": {"app.py": 1}}
    assert ctx.ota_rx is original
    assert (Path(ota.NEW_DIR) / "app.py").read_bytes() == b"n"


@pytest.mark.parametrize("version,data", [("v3", b"new"), ("v2", b"different")])
def test_begin_different_manifest_restarts(ctx, version, data):
    begin(ctx)
    chunk(ctx, b"n")
    original = ctx.ota_rx
    assert begin(ctx, version, data)["result"] == {"need": ["app.py"], "written": {"app.py": 0}}
    assert ctx.ota_rx is not original
    assert not (Path(ota.NEW_DIR) / "app.py").exists()


@pytest.mark.parametrize("name", ["ota_chunk", "ota_commit"])
def test_chunk_and_commit_without_begin(ctx, name):
    assert invoke(ctx, name)["error"]["code"] == "ota_error"
    assert ctx.reboot_requested is False


def test_commit_requests_deferred_reboot_and_clears_receiver(ctx):
    begin(ctx)
    chunk(ctx)
    assert invoke(ctx, "ota_commit")["result"] == {"version": "v2", "reboot": True}
    assert ctx.ota_rx is None
    assert ctx.reboot_requested is True
    assert ota.load_state() == {"state": "committing", "boots": 0, "version": "v2",
                                "prev": app.FW_VERSION, "config": False}
    assert machine.reset_calls == 0
    assert all(topic.endswith(b"/resp") and (retain, qos) == (False, 0)
               for topic, payload, retain, qos in ctx.link.client.publishes)


def test_failed_commit_keeps_receiver_and_does_not_reboot(ctx):
    begin(ctx)
    original = ctx.ota_rx
    assert invoke(ctx, "ota_commit")["error"]["code"] == "ota_error"
    assert ctx.ota_rx is original
    assert ctx.reboot_requested is False
    assert not Path(ota.OTA_FILE).exists()


def test_hash_mismatch_resumes_same_manifest_by_resending_whole_file(ctx):
    begin(ctx)
    rx = ctx.ota_rx
    chunk(ctx, b"bad")
    assert invoke(ctx, "ota_commit")["error"]["code"] == "ota_error"
    assert rx.progress() == {"app.py": 0}
    assert not (Path(ota.NEW_DIR) / "app.py").exists()
    assert begin(ctx)["result"] == {"need": ["app.py"], "written": {"app.py": 0}}
    assert ctx.ota_rx is rx
    assert chunk(ctx)["result"]["written"] == 3
    assert invoke(ctx, "ota_commit")["ok"] is True


def test_abort_clears_receiver_and_staged_files_and_is_repeatable(ctx):
    put(Path(ota.APP_DIR) / "app.py", b"running")
    begin(ctx)
    chunk(ctx, b"n")
    for _ in range(2):
        assert invoke(ctx, "ota_abort")["result"] == {}
        assert ctx.ota_rx is None
        assert not Path(ota.NEW_DIR).exists()
    assert (Path(ota.APP_DIR) / "app.py").read_bytes() == b"running"


def test_status_idle_receiving_trial_and_rollback(ctx):
    expected = {"version": app.FW_VERSION, "state": "ok", "boots": 0,
                "rolled_back_from": None, "receiving": None}
    assert invoke(ctx, "ota_status")["result"] == expected
    begin(ctx)
    chunk(ctx, b"n")
    assert invoke(ctx, "ota_status")["result"] == dict(expected, receiving={
        "version": "v2", "need": ["app.py"], "written": {"app.py": 1}})
    invoke(ctx, "ota_abort")
    save({"state": "trial", "version": "v2", "boots": 2})
    assert invoke(ctx, "ota_status")["result"] == dict(expected, version="v2", state="trial", boots=2)
    save({"state": "ok", "version": "v1", "boots": 0, "rolled_back_from": "v2"})
    assert invoke(ctx, "ota_status")["result"] == dict(expected, version="v1", rolled_back_from="v2")


@pytest.mark.parametrize("operation", ["chunk", "commit"])
def test_oserror_during_write_becomes_ota_error(ctx, monkeypatch, operation):
    begin(ctx)
    if operation == "commit":
        chunk(ctx)
    real_open = builtins.open
    def fail_write(path, mode="r", *args, **kwargs):
        if "w" in mode or "a" in mode:
            raise OSError("simulated flash write failure")
        return real_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(ota, "open", fail_write, raising=False)
    response = chunk(ctx) if operation == "chunk" else invoke(ctx, "ota_commit")
    assert response["ok"] is False
    assert response["error"]["code"] == "ota_error"
    assert "flash error: simulated flash write failure" in response["error"]["message"]
    assert ctx.ota_rx is not None and ctx.reboot_requested is False


def test_low_flash_is_ota_error_through_dispatch(ctx, monkeypatch):
    monkeypatch.setattr(ota.os, "statvfs", lambda path: (1, 1, 0, 0))
    assert begin(ctx)["error"]["code"] == "ota_error"
    assert ctx.ota_rx is None


@pytest.mark.parametrize("handled", [False, True])
@pytest.mark.parametrize("trial", [False, True])
def test_session_confirms_once_after_online_deadline_and_republishes_meta(
        ctx, monkeypatch, board_environment, trial, handled):
    save({"state": "trial" if trial else "ok", "boots": 1 if trial else 0, "version": "v2"})
    # Start far from boot: the deadline is measured from this connection's online time.
    board_environment[0] = 100000
    started = board_environment[0]
    assert ctx.commands_ok == 0
    assert invoke(ctx, "unknown")["ok"] is False
    assert ctx.commands_ok == 0
    if handled:
        assert invoke(ctx, "ping")["ok"] is True
        assert invoke(ctx, "ota_status")["ok"] is True
        assert ctx.commands_ok == 2
    confirm_at = []
    original_confirm = ota.confirm
    def confirm():
        confirm_at.append(board_environment[0])
        return original_confirm()
    monkeypatch.setattr(ota, "confirm", confirm)
    monkeypatch.setattr(ota, "loader_module", lambda: None)
    monkeypatch.setattr(wifi, "connected", lambda: True)
    # Jump between meaningful boundaries while keeping a bounded, real session loop.
    moments = iter([session.OTA_CONFIRM_AFTER_MS - 1, session.OTA_CONFIRM_AFTER_MS,
                    session.OTA_CONFIRM_AFTER_MS + 1, 2 * session.OTA_CONFIRM_AFTER_MS])
    def pause(seconds, feed):
        try:
            board_environment[0] = started + next(moments)
        except StopIteration:
            raise OSError("end session test")
    monkeypatch.setattr(session, "pause", pause)
    with pytest.raises(OSError, match="end session test"):
        session.run(ctx)
    assert confirm_at == ([started + session.OTA_CONFIRM_AFTER_MS] if trial and handled else [])
    client = MQTTClient.instances[-1]
    metas = [json.loads(payload)["data"] for topic, payload, retain, qos in client.publishes
             if topic.endswith(b"/meta")]
    assert [meta["ota"] for meta in metas] == (
        ["trial", "ok"] if trial and handled else ["trial"] if trial else ["ok"])
    assert ota.in_trial() is (trial and not handled)
    assert all(meta["fw"] == "v2" for meta in metas)
    assert ctx.meta_dirty is False
    assert client.sock.closed and ctx.link is None


@pytest.mark.parametrize("state", [None, {}, {"version": "v2", "state": "trial"},
                                        {"version": "", "state": "ok"}])
def test_app_fw_version_uses_ota_state_or_build_default(ctx, state):
    if state is not None:
        save(state)
    expected = "v2" if state and state.get("version") else app.FW_VERSION
    assert ctx.fw_version() == expected
    assert ctx.meta()["fw"] == expected


@pytest.mark.parametrize("watchdog_s", [0, 10])
def test_app_reuses_loader_watchdog(ctx, monkeypatch, watchdog_s):
    watchdog = machine.WDT(timeout=60000)
    monkeypatch.setattr(ota, "loader_module", lambda: SimpleNamespace(wdt=watchdog))
    def unexpected_watchdog(**kwargs):
        pytest.fail("App must reuse the loader's watchdog")
    monkeypatch.setattr(machine, "WDT", unexpected_watchdog)
    config = dict(ctx.config, watchdog_s=watchdog_s)
    instance = app.App(config, ctx.identity)
    assert instance.watchdog is watchdog
    instance.feed()
    assert watchdog.feeds == 1
