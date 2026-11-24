import pytest
import commands
from core import wifi, session


def profiles():
    return [{"ssid": "preferred", "password": "secret-one", "mqtt_host": "broker-one"},
            {"ssid": "backup", "password": "secret-two", "mqtt_host": "broker-two"},
            {"ssid": "last", "password": "secret-three"}]


def disconnected(visible):
    wlan = wifi.interface()
    wlan.connected = False
    wlan.visible = visible
    return wlan


def test_legacy_object_and_serial_without_password(capsys):
    profile = profiles()[0]
    wlan = disconnected([profile["ssid"]])
    assert wifi.connect_any(profile) is profile
    assert wlan.attempts == ["preferred"]
    output = capsys.readouterr().out
    assert "preferred" in output and "192.0.2.10" in output
    assert profile["password"] not in output


def test_visible_networks_follow_configured_priority_not_scan_order():
    wlan = disconnected(["last", "backup", "other"])
    configured = profiles()
    assert wifi.connect_any(configured) is configured[1]
    assert wlan.attempts == ["backup"]


def test_first_visible_network_fails_then_next():
    wlan = disconnected(["backup", "preferred"])
    wlan.fail_ssids.add("preferred")
    configured = profiles()
    assert wifi.connect_any(configured) is configured[1]
    assert wlan.attempts == ["preferred", "backup"]


@pytest.mark.parametrize("scan_error", [False, True])
def test_scan_failure_or_no_matching_network_tries_all_in_order(scan_error):
    wlan = disconnected(["other"])
    wlan.fail_ssids.add("preferred")
    if scan_error:
        wlan.scan_error = OSError("scan failed")
    configured = profiles()
    assert wifi.connect_any(configured) is configured[1]
    assert wlan.attempts == ["preferred", "backup"]


def test_visible_failures_do_not_attempt_invisible_networks():
    wlan = disconnected(["backup"])
    wlan.fail_ssids.add("backup")
    with pytest.raises(OSError, match="^Wi-Fi: no configured network$"):
        wifi.connect_any(profiles())
    assert wlan.attempts == ["backup"]


def test_empty_profiles_fail():
    disconnected([])
    with pytest.raises(OSError, match="^Wi-Fi: no configured network$"):
        wifi.connect_any([])


def test_already_connected_keeps_current_profile_without_scan():
    wlan = wifi.interface()
    wlan.ssid = b"backup"
    configured = profiles()
    assert wifi.connect_any(configured) is configured[1]
    assert wlan.scan_calls == 0 and not wlan.attempts


def test_connected_unconfigured_network_keeps_default_broker():
    wlan = wifi.interface()
    wlan.ssid = "from-repl"
    assert wifi.connect_any(profiles()) == {"ssid": "from-repl"}
    assert wlan.scan_calls == 0 and not wlan.attempts


def test_watchdog_around_scan_and_during_connection_wait(monkeypatch, board_environment):
    wlan = disconnected(["preferred", "backup"])
    original_scan = wlan.scan
    feeds = []

    def scan():
        assert feeds
        return original_scan()

    def connect(ssid, password):
        wlan.attempts.append(ssid)
        if ssid == "backup":
            wlan.connected = True

    monkeypatch.setattr(wlan, "scan", scan)
    monkeypatch.setattr(wlan, "connect", connect)
    assert wifi.connect_any(profiles(), 1, lambda: feeds.append(board_environment[0]))["ssid"] == "backup"
    assert wlan.attempts == ["preferred", "backup"]
    assert len(feeds) >= 24 and board_environment[0] >= 1000


@pytest.mark.parametrize("profile,host,port", [
    ({"ssid": "one", "mqtt_host": "override", "mqtt_port": 2883}, "override", 2883),
    ({"ssid": "two", "mqtt_host": "override"}, "override", 1884),
    ({"ssid": "three", "mqtt_port": 2883}, "default", 2883),
    ({"ssid": "four"}, "default", 1884),
    (None, "default", 1884),
])
def test_new_link_overrides_and_fallback(ctx, profile, host, port):
    ctx.config["mqtt"].update(host="default", port=1884)
    ctx.network = profile
    link = ctx.new_link("id", "user", "password", None)
    assert link.client.server == host
    assert link.client.port == port
    assert ctx.config["mqtt"]["host"] == "default"


def test_app_uses_selected_profile_and_updates_on_wifi_drop(ctx, monkeypatch):
    configured = profiles()
    ctx.config["wifi"] = configured
    wlan = disconnected(["backup"])
    seen = []

    def run_session(app):
        seen.append(app.network)
        assert commands.get_info(app, {})["ssid"] == app.network["ssid"]
        if len(seen) == 1:
            wlan.connected = False
            wlan.visible = ["preferred"]
            raise OSError("Wi-Fi dropped")
        raise KeyboardInterrupt()

    monkeypatch.setattr(session, "run", run_session)
    with pytest.raises(KeyboardInterrupt):
        ctx.run()
    assert seen == [configured[1], configured[0]]


def test_get_info_has_ssid(ctx):
    ctx.network = {"ssid": "Wifi nha"}
    assert commands.get_info(ctx, {})["ssid"] == "Wifi nha"


class FakeSSL:
    """Records what MicroPython's ssl module would be asked to do."""
    PROTOCOL_TLS_CLIENT, CERT_NONE, CERT_REQUIRED = 16, 0, 2

    class SSLContext:
        def __init__(self, protocol):
            self.protocol, self.verify_mode, self.cadata = protocol, None, None

        def load_verify_locations(self, cadata=None):
            self.cadata = cadata


@pytest.fixture
def fake_ssl(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "ssl", FakeSSL)
    return FakeSSL


def test_tls_link_verifies_broker_with_configured_ca(ctx, fake_ssl):
    ctx.config["mqtt"].update(host="192.168.137.1", tls={"ca": "-----BEGIN CERTIFICATE-----\n"})
    ctx.config["mqtt"].pop("port", None)
    ctx.network = None
    link = ctx.new_link("id", "user", "password", None)
    assert link.client.port == 8883 and link.tls
    context = link.client.ssl.ctx
    assert context.verify_mode == fake_ssl.CERT_REQUIRED
    assert context.cadata == b"-----BEGIN CERTIFICATE-----\n"


def test_tls_ca_file_and_insecure_and_missing_ca(ctx, fake_ssl, tmp_path):
    from core.mqtt_link import tls_context
    ca = tmp_path / "ca.pem"
    ca.write_text("PEM")
    assert tls_context({"ca_file": str(ca)}).cadata == b"PEM"
    assert tls_context({"insecure": True}).verify_mode == fake_ssl.CERT_NONE
    with pytest.raises(ValueError):
        tls_context({})


def test_plain_link_has_no_tls(ctx):
    ctx.config["mqtt"].pop("tls", None)
    ctx.network = None
    link = ctx.new_link("id", "user", "password", None)
    assert link.client.ssl is None and not link.tls
