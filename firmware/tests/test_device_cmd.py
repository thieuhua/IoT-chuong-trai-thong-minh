import importlib.util
import io
import json
from pathlib import Path
from urllib import error
import pytest


spec = importlib.util.spec_from_file_location(
    "device_cmd", Path(__file__).resolve().parents[2] / "backend" / "tools" / "device_cmd.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


@pytest.mark.parametrize("arguments,path,body", [
    (["list"], "/devices", None),
    (["esp32-ID", "ping"], "/devices/esp32-ID/commands", {"name": "ping", "args": {}, "timeout_s": 10}),
    (["esp32-ID", "read", '{"sensor":"room"}'], "/devices/esp32-ID/commands",
     {"name": "read", "args": {"sensor": "room"}, "timeout_s": 10}),
    (["esp32/a b", "servo_set", '{"angle":90}'], "/devices/esp32%2Fa%20b/commands",
     {"name": "servo_set", "args": {"angle": 90}, "timeout_s": 10}),
])
def test_cli_login_and_request(monkeypatch, capsys, arguments, path, body):
    calls = []
    monkeypatch.setattr(tool.getpass, "getpass", lambda prompt: "private-password")
    def request(base, endpoint, payload=None, token=None):
        calls.append((base, endpoint, payload, token))
        return {"access_token": "private-token"} if endpoint == "/auth/login" else {"ok": True}
    monkeypatch.setattr(tool, "request_json", request)
    assert tool.main(["--user", "admin", *arguments]) == 0
    assert calls == [("http://127.0.0.1:8000", "/auth/login",
                      {"username": "admin", "password": "private-password"}, None),
                     ("http://127.0.0.1:8000", path, body, "private-token")]
    output = capsys.readouterr().out
    assert json.loads(output) == {"ok": True}
    assert "private-" not in output


def test_urllib_request_methods_headers_and_json(monkeypatch):
    requests = []
    def open_request(req, timeout):
        requests.append(req)
        assert timeout == 20
        return io.BytesIO(b'{"ok":true}')
    monkeypatch.setattr(tool.request, "urlopen", open_request)
    assert tool.request_json("http://backend/", "/auth/login", {"username": "admin"}) == {"ok": True}
    assert tool.request_json("http://backend", "/devices", token="token") == {"ok": True}
    assert requests[0].full_url == "http://backend/auth/login"
    assert requests[0].get_method() == "POST"
    assert requests[0].get_header("Content-type") == "application/json"
    assert json.loads(requests[0].data) == {"username": "admin"}
    assert requests[1].get_method() == "GET"
    assert requests[1].get_header("Authorization") == "Bearer token"


@pytest.mark.parametrize("status", [401, 403, 404, 409, 502, 504])
def test_http_errors_are_readable_and_do_not_echo_body(monkeypatch, status):
    def fail(req, timeout):
        raise error.HTTPError(req.full_url, status, "failure", {}, io.BytesIO(b'private-response'))
    monkeypatch.setattr(tool.request, "urlopen", fail)
    with pytest.raises(ValueError) as exc:
        tool.request_json("http://backend", "/devices")
    assert "HTTP %s:" % status in str(exc.value)
    assert tool.HTTP_ERRORS[status] in str(exc.value)
    assert "private-response" not in str(exc.value)


def test_unreachable_backend_and_invalid_response(monkeypatch):
    def fail(req, timeout):
        raise error.URLError("connection refused")
    monkeypatch.setattr(tool.request, "urlopen", fail)
    with pytest.raises(ValueError, match="Cannot reach backend"):
        tool.request_json("http://backend", "/devices")
    monkeypatch.setattr(tool.request, "urlopen", lambda req, timeout: io.BytesIO(b"not JSON"))
    with pytest.raises(ValueError, match="invalid JSON"):
        tool.request_json("http://backend", "/devices")


@pytest.mark.parametrize("args", [["list", "ping"], ["id"], ["id", "ping", "[]"],
                                  ["id", "ping", "invalid"], ["--url", "ftp://backend", "list"]])
def test_invalid_input_does_not_prompt_or_contact_backend(monkeypatch, args):
    monkeypatch.setattr(tool.getpass, "getpass", lambda prompt: pytest.fail("must validate first"))
    monkeypatch.setattr(tool.request, "urlopen", lambda *a, **k: pytest.fail("no network allowed"))
    assert tool.main(["--user", "admin", *args]) == 1


def test_missing_login_token_reports_failure(monkeypatch, capsys):
    monkeypatch.setattr(tool.getpass, "getpass", lambda prompt: "secret")
    monkeypatch.setattr(tool, "request_json", lambda *a, **k: {"unexpected": "secret"})
    assert tool.main(["--user", "admin", "list"]) == 1
    assert "no access token" in capsys.readouterr().err
