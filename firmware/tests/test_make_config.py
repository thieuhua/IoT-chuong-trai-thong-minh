import copy
import importlib.util
import io
import json
from pathlib import Path
import pytest


spec = importlib.util.spec_from_file_location(
    "make_config", Path(__file__).resolve().parents[1] / "tools" / "make_config.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


@pytest.fixture
def files(tmp_path):
    config = {"wifi": [{"ssid": "home", "password": "private-wifi"}],
              "mqtt": {"host": "broker", "bootstrap_password": "private-bootstrap"}}
    paths = {name: tmp_path / name for name in ("config.json", "example.json", "source.env")}
    paths["example.json"].write_text(json.dumps(config), encoding="utf-8")
    paths["source.env"].write_text('MQTT_BOOTSTRAP_PASSWORD="dotenv-secret#value" # comment\n', encoding="utf-8")
    return paths, config


def invoke(files, *args):
    paths, _ = files
    return tool.main(["--config", str(paths["config.json"]), "--example", str(paths["example.json"]),
                      "--env", str(paths["source.env"]), *args])


def write_config(files, config=None):
    paths, default = files
    paths["config.json"].write_text(json.dumps(default if config is None else config), encoding="utf-8")


def read_config(files):
    return json.loads(files[0]["config.json"].read_text(encoding="utf-8"))


def test_init_loads_dotenv_without_printing_secrets(files, capsys):
    assert invoke(files, "init") == 0
    assert read_config(files)["mqtt"]["bootstrap_password"] == "dotenv-secret#value"
    output = capsys.readouterr()
    assert "dotenv-secret" not in output.out + output.err
    assert "private-wifi" not in output.out + output.err


def test_init_refuses_overwrite_without_force(files):
    write_config(files)
    original = files[0]["config.json"].read_bytes()
    # Refusal must happen before trying to read dotenv, too.
    files[0]["source.env"].unlink()
    assert invoke(files, "init") == 1
    assert files[0]["config.json"].read_bytes() == original
    files[0]["source.env"].write_text("MQTT_BOOTSTRAP_PASSWORD=new-secret\n", encoding="utf-8")
    assert invoke(files, "init", "--force") == 0
    assert read_config(files)["mqtt"]["bootstrap_password"] == "new-secret"


@pytest.mark.parametrize("line,value", [
    ("MQTT_BOOTSTRAP_PASSWORD=secret # comment", "secret"),
    ("export MQTT_BOOTSTRAP_PASSWORD = 'secret # with spaces'", "secret # with spaces"),
    ('MQTT_BOOTSTRAP_PASSWORD="secret=value#hash"', "secret=value#hash"),
    ("MQTT_BOOTSTRAP_PASSWORD=secret#hash", "secret#hash"),
])
def test_dotenv_syntax(files, line, value):
    files[0]["source.env"].write_text(line, encoding="utf-8")
    assert invoke(files, "init") == 0
    assert read_config(files)["mqtt"]["bootstrap_password"] == value


@pytest.mark.parametrize("line", ["OTHER=value", "MQTT_BOOTSTRAP_PASSWORD=", 'MQTT_BOOTSTRAP_PASSWORD="unclosed'])
def test_init_invalid_dotenv_does_not_create_config(files, line):
    files[0]["source.env"].write_text(line, encoding="utf-8")
    assert invoke(files, "init") == 1
    assert not files[0]["config.json"].exists()


def test_add_and_update_priority_legacy_config(files, monkeypatch, capsys):
    config = copy.deepcopy(files[1])
    config["wifi"] = config["wifi"][0]
    write_config(files, config)
    monkeypatch.setattr(tool.getpass, "getpass", lambda prompt: "new-private-password")
    assert invoke(files, "wifi-add", "office", "--mqtt-host", "office-broker", "--mqtt-port", "2883") == 0
    assert [p["ssid"] for p in read_config(files)["wifi"]] == ["home", "office"]
    assert invoke(files, "wifi-add", "office", "--first") == 0
    profiles = read_config(files)["wifi"]
    assert [p["ssid"] for p in profiles] == ["office", "home"]
    assert profiles[0] == {"ssid": "office", "password": "new-private-password",
                           "mqtt_host": "office-broker", "mqtt_port": 2883}
    assert "new-private-password" not in capsys.readouterr().out


def test_stdin_password_and_first_insertion(files, monkeypatch):
    write_config(files)
    monkeypatch.setattr(tool.sys, "stdin", io.StringIO("stdin-secret\n"))
    monkeypatch.setattr(tool.getpass, "getpass", lambda prompt: pytest.fail("getpass must not run"))
    assert invoke(files, "wifi-add", "guest", "--password-stdin", "--first") == 0
    assert read_config(files)["wifi"][0] == {"ssid": "guest", "password": "stdin-secret"}


def test_stdin_eof_preserves_file(files, monkeypatch):
    write_config(files)
    monkeypatch.setattr(tool.sys, "stdin", io.StringIO(""))
    assert invoke(files, "wifi-add", "guest", "--password-stdin") == 1
    assert read_config(files) == files[1]


def test_remove_and_migrate_legacy_format(files):
    config = copy.deepcopy(files[1])
    config["wifi"] = config["wifi"][0]
    write_config(files, config)
    assert invoke(files, "wifi-remove", "missing") == 1
    assert read_config(files) == config
    assert invoke(files, "wifi-remove", "home") == 0
    assert read_config(files)["wifi"] == []
    assert invoke(files, "check") == 1


def test_list_priority_hosts_and_no_passwords(files, capsys):
    config = copy.deepcopy(files[1])
    config["wifi"].insert(0, {"ssid": "office", "password": "other-secret", "mqtt_host": "office-broker"})
    write_config(files, config)
    original = files[0]["config.json"].read_bytes()
    assert invoke(files, "wifi-list") == 0
    output = capsys.readouterr().out
    assert output.splitlines() == ["1. office mqtt_host=office-broker", "2. home mqtt_host=broker"]
    assert "private-wifi" not in output and "other-secret" not in output
    assert "private-bootstrap" not in output
    assert files[0]["config.json"].read_bytes() == original


def test_check_legacy_and_placeholder_warnings_do_not_expose_values(files, capsys):
    config = copy.deepcopy(files[1])
    config["wifi"] = {"ssid": "YOUR_HOME", "password": "YOUR_SECRET_PASSWORD"}
    config["mqtt"]["bootstrap_password"] = "FROM_SECRET_SOURCE"
    write_config(files, config)
    assert invoke(files, "check") == 0
    output = capsys.readouterr().out
    assert "config.wifi.password" in output and "config.mqtt.bootstrap_password" in output
    assert "YOUR_SECRET_PASSWORD" not in output and "FROM_SECRET_SOURCE" not in output


@pytest.mark.parametrize("wifi", [[], None, "bad", [None], [{}], [{"ssid": "x"}],
    [{"ssid": "", "password": "p"}], [{"ssid": "x", "password": 5}],
    [{"ssid": "x", "password": "p", "mqtt_host": ""}],
    [{"ssid": "x", "password": "p", "mqtt_port": True}],
    [{"ssid": "x", "password": "p", "mqtt_port": 0}],
    [{"ssid": "x", "password": "p", "mqtt_port": 65536}]])
def test_check_invalid_networks(files, wifi):
    config = dict(files[1], wifi=wifi)
    write_config(files, config)
    assert invoke(files, "check") == 1


@pytest.mark.parametrize("mqtt", [None, {}, {"host": "broker"},
    {"host": "", "bootstrap_password": "p"},
    {"host": "broker", "bootstrap_password": "p", "port": "1883"}])
def test_check_missing_or_invalid_mqtt_fields(files, mqtt):
    write_config(files, dict(files[1], mqtt=mqtt))
    assert invoke(files, "check") == 1


def test_invalid_json_and_nonobject_fail(files, capsys):
    for text in ('{"password":"private-wifi", broken}', '[]'):
        files[0]["config.json"].write_text(text, encoding="utf-8")
        assert invoke(files, "check") == 1
    output = capsys.readouterr()
    assert "private-wifi" not in output.out + output.err


def test_failed_atomic_save_preserves_old_config(files, monkeypatch):
    write_config(files)
    original = files[0]["config.json"].read_bytes()
    def fail(source, destination):
        raise OSError("replace failed")
    monkeypatch.setattr(tool.os, "replace", fail)
    with pytest.raises(OSError, match="replace failed"):
        tool.save_config(files[0]["config.json"], {"new": True})
    assert files[0]["config.json"].read_bytes() == original
    assert not list(files[0]["config.json"].parent.glob("config.json.*"))


def test_password_command_line_argument_is_rejected(files):
    with pytest.raises(SystemExit) as exc:
        invoke(files, "wifi-add", "home", "--password", "secret")
    assert exc.value.code == 2
