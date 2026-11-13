"""Stable loader recovery, using real files for each interrupted install step."""
import json
from pathlib import Path

import machine
import pytest


def put(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data)


def state(loader, **extra):
    result = {"state": "committing", "version": "new", "prev": "old", "config": True}
    result.update(extra)
    put(loader.OTA_FILE, json.dumps(result))
    return result


@pytest.mark.parametrize("contents", [None, "{broken", "[]", "null"])
def test_missing_or_corrupt_state_leaves_files_alone(loader, tmp_path, contents):
    put(tmp_path / "app/app.py", "old")
    put(tmp_path / "app_new/app.py", "new")
    if contents is not None:
        put(loader.OTA_FILE, contents)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert loader.check_ota() == {}
    assert before == {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert loader.wdt is None and loader._timer is None
    assert machine.reset_calls == 0


@pytest.mark.parametrize("config", [False, True])
def test_install_saves_trial_zero_then_counts_boot(loader, tmp_path, config):
    put(tmp_path / "app/app.py", "old")
    put(tmp_path / "app_new/app.py", "new")
    put(loader.CONFIG, "old config")
    if config:
        put(tmp_path / "app_new/config.json", "new config")
    pending = state(loader, config=config)
    loader._install(pending)
    assert loader.load_state() == dict(pending, state="trial", boots=0)
    assert (tmp_path / "app/app.py").read_text() == "new"
    assert (tmp_path / "app_old/app.py").read_text() == "old"
    assert not Path(loader.NEW_DIR).exists()
    assert not (tmp_path / "app/config.json").exists()
    assert Path(loader.CONFIG).read_text() == ("new config" if config else "old config")
    assert Path(loader.CONFIG_OLD).exists() is config
    if config:
        assert Path(loader.CONFIG_OLD).read_text() == "old config"
    assert loader.check_ota()["boots"] == 1


# Each boundary corresponds to a completed persistent action in _install/save_state:
# remove old config backup, move config aside, install config, remove old app backup,
# move app aside, install app, write state.tmp, rename state.tmp -> state.
@pytest.mark.parametrize("cut", range(9))
def test_install_recovers_after_each_step(loader, tmp_path, cut):
    if cut < 1:
        put(loader.CONFIG_OLD, "stale config")
    if cut < 2:
        put(loader.CONFIG, "old config")
    else:
        put(loader.CONFIG_OLD, "old config")
    if cut < 3:
        put(tmp_path / "app_new/config.json", "new config")
    else:
        put(loader.CONFIG, "new config")
    if cut < 4:
        put(tmp_path / "app_old/app.py", "stale app")
    if cut < 5:
        put(tmp_path / "app/app.py", "old")
    else:
        put(tmp_path / "app_old/app.py", "old")
    put(tmp_path / ("app_new" if cut < 6 else "app") / "app.py", "new")
    pending = state(loader)
    if cut >= 7:
        put(loader.OTA_FILE + ".tmp", json.dumps(dict(pending, state="trial", boots=0)))
    if cut == 8:
        Path(loader.OTA_FILE + ".tmp").replace(loader.OTA_FILE)

    result = loader.check_ota()
    assert result == dict(pending, state="trial", boots=1)
    assert loader.load_state() == result
    assert (tmp_path / "app/app.py").read_text() == "new"
    assert (tmp_path / "app_old/app.py").read_text() == "old"
    assert Path(loader.CONFIG).read_text() == "new config"
    assert Path(loader.CONFIG_OLD).read_text() == "old config"
    assert not Path(loader.NEW_DIR).exists()
    assert not Path(loader.OTA_FILE + ".tmp").exists()
    assert machine.reset_calls == 0


@pytest.mark.parametrize("cut", range(6))
def test_install_without_config_recovers_after_each_step(loader, tmp_path, cut):
    # Boundaries: start, remove stale backup, move app aside, install app,
    # write state.tmp, replace ota.json. Config is outside this update.
    put(loader.CONFIG, "keep config")
    if cut < 1:
        put(tmp_path / "app_old/app.py", "stale app")
    put(tmp_path / ("app" if cut < 2 else "app_old") / "app.py", "old")
    put(tmp_path / ("app_new" if cut < 3 else "app") / "app.py", "new")
    pending = state(loader, config=False)
    if cut >= 4:
        put(loader.OTA_FILE + ".tmp", json.dumps(dict(pending, state="trial", boots=0)))
    if cut == 5:
        Path(loader.OTA_FILE + ".tmp").replace(loader.OTA_FILE)
    assert loader.check_ota() == dict(pending, state="trial", boots=1)
    assert (tmp_path / "app/app.py").read_text() == "new"
    assert (tmp_path / "app_old/app.py").read_text() == "old"
    assert Path(loader.CONFIG).read_text() == "keep config"
    assert not Path(loader.CONFIG_OLD).exists()
    assert not Path(loader.NEW_DIR).exists()
    assert not Path(loader.OTA_FILE + ".tmp").exists()


@pytest.mark.parametrize("config", [False, True])
def test_trial_boots_persist_then_roll_back(loader, tmp_path, config):
    put(tmp_path / "app/app.py", "new")
    put(tmp_path / "app_old/app.py", "old")
    put(loader.CONFIG, "new config")
    put(loader.CONFIG_OLD, "old config")
    state(loader, state="trial", boots=0, config=config)
    for boot in (1, 2):
        assert loader.check_ota()["boots"] == boot
        assert loader.load_state()["boots"] == boot
        assert (tmp_path / "app/app.py").read_text() == "new"
    assert loader.check_ota() == {"state": "ok", "boots": 0, "version": "old",
                                  "rolled_back_from": "new"}
    assert (tmp_path / "app/app.py").read_text() == "old"
    assert not Path(loader.OLD_DIR).exists()
    assert Path(loader.CONFIG).read_text() == ("old config" if config else "new config")
    assert Path(loader.CONFIG_OLD).exists() is (not config)
    assert loader.check_ota() == loader.load_state()
    assert machine.reset_calls == 0


def test_third_boot_without_backup_gives_up(loader, tmp_path):
    put(tmp_path / "app/app.py", "new")
    state(loader, state="trial", boots=2)
    expected = {"state": "ok", "boots": 0, "version": "new"}
    assert loader.check_ota() == expected
    assert loader.check_ota() == expected
    assert (tmp_path / "app/app.py").read_text() == "new"
    assert loader.wdt is None and loader._timer is None
    assert machine.reset_calls == 0


@pytest.mark.parametrize("confirmed", [False, True])
def test_trial_arms_watchdog_and_confirm_deadline(loader, confirmed):
    state(loader, state="trial", boots=0)
    loader.check_ota()
    assert loader.wdt.timeout == 60000
    loader.wdt.feed()
    assert loader.wdt.feeds == 1
    timer = loader._timer
    assert (timer.id, timer.mode, timer.period, timer.active) == (1, machine.Timer.ONE_SHOT, 300000, True)
    loader.confirmed = confirmed
    timer.fire()
    assert machine.reset_calls == (0 if confirmed else 1)
    timer.fire()
    assert machine.reset_calls == (0 if confirmed else 1)
