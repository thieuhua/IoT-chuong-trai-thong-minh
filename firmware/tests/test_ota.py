import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from core import ota


def entry(path="app.py", data=b"new"):
    return {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def encoded(data):
    return base64.b64encode(data).decode()


def put(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def save(state):
    Path(ota.OTA_FILE).write_text(json.dumps(state))


@pytest.mark.parametrize("path", [None, 1, "", "/app.py", "../app.py", "core/../app.py",
    "core//app.py", "main.py", "boot.py", "App.py", "a b.py", "a\\b.py", "a:main.py",
    "a\x00.py", "a.txt", "a.py/", "x" * 62 + ".py"])
def test_reject_invalid_paths(path):
    with pytest.raises(ota.OtaError) as exc:
        ota.check_path(path)
    assert exc.value.code == "bad_args"


@pytest.mark.parametrize("path", ["app.py", "core/util.py", "driver.mpy", "config.json",
                                       "x" * 61 + ".py"])
def test_accept_valid_paths(path):
    assert ota.check_path(path) == path


@pytest.mark.parametrize("version", [None, 1, "", "x" * 41])
def test_invalid_version(version):
    with pytest.raises(ota.OtaError) as exc:
        ota.Receiver(version, [entry()])
    assert exc.value.code == "bad_args"
    assert not Path(ota.NEW_DIR).exists()


@pytest.mark.parametrize("files", [None, {}, [], [entry()] * 65, [None], [{}],
    [entry("util.py")], [entry(), entry()],
    [dict(entry(), size=True)], [dict(entry(), size=-1)], [dict(entry(), size=1.5)],
    [dict(entry(), size="3")], [dict(entry(), sha256=None)], [dict(entry(), sha256="abc")]])
def test_invalid_files(files):
    with pytest.raises(ota.OtaError) as exc:
        ota.Receiver("v2", files)
    assert exc.value.code == "bad_args"
    assert not Path(ota.NEW_DIR).exists()


@pytest.mark.parametrize("state", ["trial", "committing"])
def test_refuse_update_while_pending(state):
    save({"state": state})
    put(Path(ota.NEW_DIR) / "sentinel.py", b"pending")
    put(Path(ota.OLD_DIR) / "app.py", b"backup")
    with pytest.raises(ota.OtaError) as exc:
        ota.Receiver("v2", [entry()])
    assert exc.value.code == "ota_error"
    assert (Path(ota.NEW_DIR) / "sentinel.py").read_bytes() == b"pending"
    assert (Path(ota.OLD_DIR) / "app.py").read_bytes() == b"backup"


def test_need_compares_app_and_root_config_and_creates_empty_files():
    put(Path(ota.APP_DIR) / "app.py", b"same")
    put(ota.CONFIG_FILE, b"config")
    put(Path(ota.APP_DIR) / "config.json", b"wrong place")
    put(Path(ota.APP_DIR) / "core/util.py", b"old")
    put(Path(ota.NEW_DIR) / "stale.py", b"stale")
    put(Path(ota.OLD_DIR) / "stale.py", b"stale")
    rx = ota.Receiver("v2", [entry(data=b"same"), entry("config.json", b"config"),
                              entry("core/util.py"), entry("core/empty.py", b"")])
    assert rx.need() == ["core/util.py"]
    assert rx.progress() == {"core/util.py": 0, "core/empty.py": 0}
    assert rx.files["app.py"]["need"] is False
    assert rx.files["config.json"]["need"] is False
    assert (Path(ota.NEW_DIR) / "core/empty.py").read_bytes() == b""
    assert not (Path(ota.NEW_DIR) / "stale.py").exists()
    assert not Path(ota.OLD_DIR).exists()


def test_chunk_order_duplicate_gap_and_completion():
    rx = ota.Receiver("v2", [entry(data=b"abcdef")])
    assert rx.chunk("app.py", 0, encoded(b"abc")) == 3
    assert rx.chunk("app.py", 0, encoded(b"xxx")) == 3
    assert (Path(ota.NEW_DIR) / "app.py").read_bytes() == b"abc"
    with pytest.raises(ota.OtaError, match="expected offset 3") as exc:
        rx.chunk("app.py", 4, encoded(b"d"))
    assert exc.value.code == "bad_args"
    assert rx.progress() == {"app.py": 3}
    assert rx.chunk("app.py", 3, encoded(b"def")) == 6
    assert (Path(ota.NEW_DIR) / "app.py").read_bytes() == b"abcdef"


@pytest.mark.parametrize("path,offset,data,message", [
    ("missing.py", 0, "YQ==", "path not expected"),
    ("app.py", True, "YQ==", "offset must be int"),
    ("app.py", "0", "YQ==", "offset must be int"),
    ("app.py", 0, b"YQ==", "data base64 text"),
    ("app.py", 0, "a", "not base64"),
    ("app.py", 0, "YWJjZA==", "beyond declared size")])
def test_chunk_rejects_invalid_input_without_progress(path, offset, data, message):
    rx = ota.Receiver("v2", [entry()])
    with pytest.raises(ota.OtaError, match=message) as exc:
        rx.chunk(path, offset, data)
    assert exc.value.code == "bad_args"
    assert rx.progress() == {"app.py": 0}
    assert not (Path(ota.NEW_DIR) / "app.py").exists()


def test_chunk_refuses_unchanged_file():
    put(Path(ota.APP_DIR) / "app.py", b"new")
    rx = ota.Receiver("v2", [entry()])
    with pytest.raises(ota.OtaError, match="path not expected"):
        rx.chunk("app.py", 0, encoded(b"new"))


@pytest.mark.parametrize("data,message", [(b"n", "incomplete"), (b"bad", "sha256 mismatch")])
def test_commit_rejects_incomplete_or_bad_hash(data, message):
    rx = ota.Receiver("v2", [entry()])
    rx.chunk("app.py", 0, encoded(data))
    with pytest.raises(ota.OtaError, match=message) as exc:
        rx.commit("v1")
    assert exc.value.code == "ota_error"
    assert not Path(ota.OTA_FILE).exists()


@pytest.mark.parametrize("config_changed", [False, True])
def test_commit_copies_unchanged_app_excludes_unchanged_config(config_changed):
    put(Path(ota.APP_DIR) / "app.py", b"same app")
    put(Path(ota.APP_DIR) / "core/util.py", b"same utility")
    put(Path(ota.APP_DIR) / "removed.py", b"not in manifest")
    put(ota.CONFIG_FILE, b"old config")
    config = b"new config" if config_changed else b"old config"
    rx = ota.Receiver("v2", [entry(data=b"same app"), entry("core/util.py", b"same utility"),
                              entry("changed.py", b"new"), entry("empty.json", b""),
                              entry("config.json", config)])
    rx.chunk("changed.py", 0, encoded(b"new"))
    if config_changed:
        rx.chunk("config.json", 0, encoded(config))
    rx.commit("v1")
    assert ota.load_state() == {"state": "committing", "boots": 0, "version": "v2",
                                "prev": "v1", "config": config_changed}
    expected = {"app.py": b"same app", "core/util.py": b"same utility",
                "changed.py": b"new", "empty.json": b""}
    if config_changed:
        expected["config.json"] = config
    assert {p.relative_to(ota.NEW_DIR).as_posix(): p.read_bytes()
            for p in Path(ota.NEW_DIR).rglob("*") if p.is_file()} == expected
    assert Path(ota.CONFIG_FILE).read_bytes() == b"old config"
    assert (Path(ota.APP_DIR) / "removed.py").read_bytes() == b"not in manifest"


def test_commit_without_config_sets_false_flag():
    rx = ota.Receiver("v2", [entry()])
    rx.chunk("app.py", 0, encoded(b"new"))
    rx.commit("v1")
    assert ota.load_state()["config"] is False


def test_insufficient_flash(monkeypatch):
    monkeypatch.setattr(ota.os, "statvfs", lambda path: (1, 1, 1, ota.FREE_MARGIN + 2))
    with pytest.raises(ota.OtaError, match="not enough flash") as exc:
        ota.Receiver("v2", [entry()])
    assert exc.value.code == "ota_error"
    assert not Path(ota.NEW_DIR).exists()


@pytest.mark.parametrize("loader_present", [False, True])
def test_confirm_trial_cleans_backup_and_notifies_loader(monkeypatch, loader_present):
    loader = SimpleNamespace(confirmed=False) if loader_present else None
    monkeypatch.setattr(ota, "loader_module", lambda: loader)
    save({"state": "trial", "boots": 2, "version": "v2", "prev": "v1", "config": True})
    put(Path(ota.OLD_DIR) / "nested/old.py", b"old")
    assert ota.in_trial() is True
    assert ota.confirm() is True
    assert ota.load_state() == {"state": "ok", "boots": 0, "version": "v2", "prev": "v1", "config": True}
    assert not Path(ota.OLD_DIR).exists()
    assert ota.in_trial() is False
    if loader_present:
        assert loader.confirmed is True
    assert ota.confirm() is False


def test_confirm_ok_is_noop(monkeypatch):
    save({"state": "ok", "version": "v1"})
    put(Path(ota.OLD_DIR) / "old.py", b"old")
    loader = SimpleNamespace(confirmed=False)
    monkeypatch.setattr(ota, "loader_module", lambda: loader)
    before = Path(ota.OTA_FILE).read_bytes()
    assert ota.confirm() is False
    assert Path(ota.OTA_FILE).read_bytes() == before
    assert (Path(ota.OLD_DIR) / "old.py").exists()
    assert loader.confirmed is False


def test_abort_refused_after_commit_preserves_staged_files():
    rx = ota.Receiver("v2", [entry()])
    rx.chunk("app.py", 0, encoded(b"new"))
    rx.commit("v1")
    before = Path(ota.OTA_FILE).read_bytes()
    with pytest.raises(ota.OtaError, match="already committed") as exc:
        ota.abort()
    assert exc.value.code == "ota_error"
    assert (Path(ota.NEW_DIR) / "app.py").read_bytes() == b"new"
    assert Path(ota.OTA_FILE).read_bytes() == before


@pytest.mark.parametrize("offset", [0, 1])
def test_partial_write_failure_removes_file_and_resets_progress(monkeypatch, offset):
    rx = ota.Receiver("v2", [entry()])
    if offset:
        rx.chunk("app.py", 0, encoded(b"n"))
    target = Path(ota.NEW_DIR) / "app.py"
    class BrokenWrite:
        def __enter__(self):
            self.stream = open(target, "ab" if offset else "wb")
            return self
        def write(self, data):
            self.stream.write(data[:1])
            self.stream.flush()
            raise OSError("partial flash write")
        def __exit__(self, *args):
            self.stream.close()
    with monkeypatch.context() as patch:
        patch.setattr(ota, "open", lambda *args: BrokenWrite(), raising=False)
        with pytest.raises(OSError, match="partial flash write"):
            rx.chunk("app.py", offset, encoded(b"new"[offset:]))
    assert rx.progress() == {"app.py": 0}
    assert not target.exists()
    assert rx.chunk("app.py", 0, encoded(b"new")) == 3
    rx.commit("v1")


@pytest.mark.parametrize("data", ["!!!!", "YWJj!!!!", "YWJj\n", "YW$j"])
def test_invalid_base64_characters_rejected_without_writing(data):
    rx = ota.Receiver("v2", [entry(data=b"abcdef")])
    with pytest.raises(ota.OtaError, match="base64") as exc:
        rx.chunk("app.py", 0, data)
    assert exc.value.code == "bad_args"
    assert rx.progress() == {"app.py": 0}
    assert not (Path(ota.NEW_DIR) / "app.py").exists()
