"""DB-backed coverage for alert callbacks, command history and barn reads."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.main import app, get_current_user, get_db, register_alert_callbacks
from app.services.alert_engine import AlertEngine
from iot_core import CommandFailed, CommandTimeout, DeviceOffline
from iot_core.models import Readings, StatusEvent, TelemetryRecord
from test_app import http


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'mvp.db'}",
                           connect_args={"check_same_thread": False})
    tables = [models.User, models.Barn, models.BarnAssignment, models.Device,
              models.Command, models.AlertRule, models.Alert]
    Base.metadata.create_all(engine, tables=[model.__table__ for model in tables])
    with engine.begin() as connection:
        connection.exec_driver_sql("""CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id VARCHAR(36),
            action VARCHAR(100), target VARCHAR(255), result VARCHAR(100), ts DATETIME)""")
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        db.add_all([models.Barn(id="barn-1", name="One"), models.Barn(id="barn-2", name="Two")])
        for key, role in [("admin", "Admin"), ("operator", "Operator"), ("viewer", "Viewer")]:
            db.add(models.User(id=key, username=key, role=role, password_hash="unused"))
        db.flush()
        db.add_all([
            models.BarnAssignment(barn_id="barn-1", user_id="operator", access_level="Operator"),
            models.BarnAssignment(barn_id="barn-1", user_id="viewer", access_level="Viewer"),
            models.Device(device_id="dev-1", hw_id="hw-1", barn_id="barn-1", status="online"),
            models.Device(device_id="dev-2", hw_id="hw-2", barn_id="barn-2", status="online"),
            models.Device(device_id="unassigned", hw_id="hw-3", status="online"),
        ])
        db.commit()
    yield factory
    engine.dispose()


@pytest.fixture
def access(database):
    old = app.dependency_overrides.copy()
    user = SimpleNamespace(id="operator", role="Operator")

    def session():
        with database() as db:
            yield db

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = lambda: user
    yield user
    app.dependency_overrides.clear()
    app.dependency_overrides.update(old)


def sample(value=38, device_id="dev-1", errors=None):
    values = {} if value is None else {"room": {"temperature": value}}
    return TelemetryRecord(device_id, datetime.now(timezone.utc), None, Readings(values, errors or {}))


def add_rule(database, **changes):
    data = dict(id="rule-1", barn_id="barn-1", metric="temperature", op=">",
                threshold=35, hold_samples=2, severity="warning")
    with database() as db:
        db.add(models.AlertRule(**(data | changes)))
        db.commit()


@pytest.mark.parametrize("reset", [35, None, "bad", True, float("nan")])
async def test_alerts_require_consecutive_valid_samples_and_do_not_duplicate(database, reset):
    add_rule(database)
    engine = AlertEngine(database)
    await engine.on_telemetry(sample())
    await engine.on_telemetry(sample(reset))
    await engine.on_telemetry(sample())
    with database() as db:
        assert db.query(models.Alert).count() == 0
    await asyncio.gather(*(engine.on_telemetry(sample()) for _ in range(4)))
    with database() as db:
        rows = db.query(models.Alert).all()
        assert len(rows) == 1
        assert (rows[0].rule_id, rows[0].device_id, rows[0].status, rows[0].severity) == (
            "rule-1", "dev-1", "open", "warning")
        rows[0].status = "closed"
        db.commit()
    await engine.on_telemetry(sample())
    with database() as db:
        assert db.query(models.Alert).filter_by(status="open").count() == 1
        assert db.query(models.Alert).count() == 2


async def test_alert_rule_scope_sensor_errors_and_offline_reset(database):
    add_rule(database, metric="room.temperature")
    engine = AlertEngine(database)
    await engine.on_telemetry(sample(device_id="dev-2"))
    await engine.on_telemetry(sample(device_id="unassigned"))
    await engine.on_telemetry(sample())
    await engine.on_telemetry(sample(errors={"room": "timeout"}))
    await engine.on_telemetry(sample())
    with database() as db:
        assert db.query(models.Alert).count() == 0
    offline = StatusEvent("dev-1", False, "lost", datetime.now(timezone.utc))
    await asyncio.gather(engine.on_status_change(offline), engine.on_status_change(offline))
    await engine.on_status_change(StatusEvent("dev-1", True, None, datetime.now(timezone.utc)))
    await engine.on_telemetry(sample())
    with database() as db:
        row = db.query(models.Alert).one()
        assert (row.rule_id, row.severity, row.status) == (None, "critical", "open")
    await engine.on_telemetry(sample())
    with database() as db:
        assert db.query(models.Alert).count() == 2


@pytest.mark.parametrize("op,threshold", [("<", 39), ("<=", 38), (">=", 38), ("==", 38), ("!=", 37)])
async def test_alert_comparisons(database, op, threshold):
    add_rule(database, op=op, threshold=threshold, hold_samples=1)
    await AlertEngine(database).on_telemetry(sample())
    with database() as db:
        assert db.query(models.Alert).count() == 1


async def test_registered_callbacks_are_idempotent_and_use_worker_sessions(database, gateway, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "SessionLocal", database)
    app.state.gateway = gateway
    add_rule(database, hold_samples=1)
    register_alert_callbacks(app)
    register_alert_callbacks(app)
    try:
        assert len(gateway._events["telemetry"]) == 1
        assert len(gateway._events["status"]) == 1
        await gateway._emit("telemetry", sample())
        await gateway._emit("status", StatusEvent("dev-1", False, None, datetime.now(timezone.utc)))
        with database() as db:
            assert db.query(models.Alert).count() == 2
    finally:
        for unsubscribe in app.state.alert_unsubscribes:
            unsubscribe()
        app.state.alert_gateway = None


async def test_lifespan_registers_and_removes_alert_callbacks(database, gateway, monkeypatch):
    import app.main as main

    @asynccontextmanager
    async def configured_gateway(*args, **kwargs):
        yield gateway

    monkeypatch.setattr(main, "SessionLocal", database)
    monkeypatch.setattr(main, "DATABASE_URL", None)
    monkeypatch.setattr(main, "test_db_connection", lambda: True)
    monkeypatch.setattr(main.GatewayConfig, "from_env", lambda _: None)
    monkeypatch.setattr(main.DeviceGateway, "from_config", configured_gateway)
    add_rule(database, hold_samples=1)
    async with main.lifespan(app):
        assert len(gateway._events["telemetry"]) == 1
        await gateway._emit("telemetry", sample())
        with database() as db:
            assert db.query(models.Alert).count() == 1
    assert not gateway._events["telemetry"] and not gateway._events["status"]


async def test_hold_samples_are_independent_per_device(database):
    add_rule(database)
    with database() as db:
        db.get(models.Device, "dev-2").barn_id = "barn-1"
        db.commit()
    engine = AlertEngine(database)
    await engine.on_telemetry(sample())
    await engine.on_telemetry(sample(device_id="dev-2"))
    with database() as db:
        assert db.query(models.Alert).count() == 0
    await engine.on_telemetry(sample())
    with database() as db:
        assert db.query(models.Alert).one().device_id == "dev-1"


async def test_device_and_barn_commands_share_history(database, gateway, access, monkeypatch):
    calls = []

    async def send(device_id, name, args, timeout):
        # Pending must already be committed before MQTT is sent.
        with database() as db:
            assert db.query(models.Command).filter_by(status="pending").count() == 1
        calls.append((device_id, name, args))
        return {"on": True}

    monkeypatch.setattr(gateway, "send_command", send)
    assert await http(gateway, "POST", "/devices/dev-1/commands",
                      {"name": "relay_set", "args": {"on": True}}) == (200, {"on": True})
    status, row = await http(gateway, "POST", "/barns/barn-1/commands",
                             {"action": "relay_set", "params": {"on": True}})
    assert status == 200 and row["status"] == "success" and row["acked_at"]
    assert calls == [("dev-1", "relay_set", {"on": True})] * 2
    access.id, access.role = "viewer", "Viewer"
    status, rows = await http(gateway, "GET", "/barns/barn-1/commands")
    assert status == 200 and len(rows) == 2
    assert rows[0]["issued_at"] >= rows[1]["issued_at"]
    assert all(row["status"] == "success" and row["acked_at"] for row in rows)
    assert (await http(gateway, "POST", "/barns/barn-1/commands", {"action": "ping"}))[0] == 403
    assert len(calls) == 2


@pytest.mark.parametrize("path,body", [
    ("/devices/dev-1/commands", {"name": "ping"}),
    ("/barns/barn-1/commands", {"action": "ping"}),
])
@pytest.mark.parametrize("error,status", [(CommandTimeout("timeout"), 504),
    (CommandFailed("bad_args", "bad"), 502), (DeviceOffline("dev-1"), 409)])
async def test_command_failures_are_recorded(database, gateway, access, monkeypatch, path, body, error, status):
    async def fail(*args):
        raise error
    monkeypatch.setattr(gateway, "send_command", fail)
    assert (await http(gateway, "POST", path, body))[0] == status
    with database() as db:
        row = db.query(models.Command).one()
        assert row.status == "failed" and row.acked_at is not None


async def test_barn_commands_reject_wrong_barn_and_allow_admin(database, gateway, access, monkeypatch):
    calls = []

    async def send(*args):
        calls.append(args)
        return {}

    monkeypatch.setattr(gateway, "send_command", send)
    assert (await http(gateway, "GET", "/barns/barn-2/commands"))[0] == 403
    assert (await http(gateway, "POST", "/barns/barn-2/commands", {"action": "ping"}))[0] == 403
    assert not calls
    access.id, access.role = "admin", "Admin"
    assert (await http(gateway, "POST", "/barns/barn-2/commands", {"action": "ping"}))[0] == 200
    assert calls[0][0] == "dev-2"
    with database() as db:
        db.add(models.Barn(id="empty", name="Empty"))
        db.commit()
    assert (await http(gateway, "POST", "/barns/empty/commands", {"action": "ping"}))[0] == 404


@pytest.mark.parametrize("role,user_id", [("Operator", "operator"), ("Viewer", "viewer"), ("Admin", "admin")])
async def test_all_device_reads_check_current_barn_assignment(database, gateway, access, monkeypatch, role, user_id):
    access.id, access.role = user_id, role
    calls = []

    async def result(device_id, *args):
        calls.append(device_id)
        return {"device_id": device_id}

    for name in ["get_device", "read_all", "read_sensor", "telemetry_history", "latest_telemetry"]:
        monkeypatch.setattr(gateway, name, result)
    suffixes = ["", "/readings", "/sensors/room", "/telemetry", "/telemetry/latest"]
    for device_id in ["dev-1", "dev-2", "unassigned"]:
        expected = 200 if role == "Admin" or device_id == "dev-1" else 403
        before = len(calls)
        for suffix in suffixes:
            assert (await http(gateway, "GET", f"/devices/{device_id}{suffix}"))[0] == expected
        assert len(calls) - before == (5 if expected == 200 else 0)
    if role != "Admin":
        with database() as db:
            db.query(models.BarnAssignment).filter_by(user_id=user_id).delete()
            db.commit()
        assert (await http(gateway, "GET", "/devices/dev-1"))[0] == 403


async def test_device_list_is_filtered_and_includes_barn_for_dashboard(database, gateway, access, monkeypatch):
    async def devices(online):
        assert online is None
        return [dict(device_id=key) for key in ["dev-1", "dev-2", "unassigned"]]

    monkeypatch.setattr(gateway, "list_devices", devices)
    for user_id, role in [("operator", "Operator"), ("viewer", "Viewer")]:
        access.id, access.role = user_id, role
        assert await http(gateway, "GET", "/devices") == (200, [{"device_id": "dev-1", "barn_id": "barn-1"}])
    access.id, access.role = "admin", "Admin"
    status, rows = await http(gateway, "GET", "/devices")
    assert status == 200 and {row["device_id"] for row in rows} == {"dev-1", "dev-2", "unassigned"}


async def test_admin_can_create_demo_alert_rule(database, gateway, access):
    body = dict(metric="temperature", op=">", threshold=35, severity="warning", hold_samples=1)
    for user_id, role in [("operator", "Operator"), ("viewer", "Viewer")]:
        access.id, access.role = user_id, role
        assert (await http(gateway, "POST", "/barns/barn-1/alert-rules", body))[0] == 403
    access.id, access.role = "admin", "Admin"
    status, rule = await http(gateway, "POST", "/barns/barn-1/alert-rules", body)
    assert status == 201 and rule["barn_id"] == "barn-1"
    await AlertEngine(database).on_telemetry(sample())
    with database() as db:
        assert db.query(models.Alert).one().rule_id == rule["id"]
    assert (await http(gateway, "POST", "/barns/missing/alert-rules", body))[0] == 404
