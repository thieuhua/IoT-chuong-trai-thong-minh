"""Lifecycle API authorization, persistence and gateway callback integration."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from threading import get_ident
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.main import app, get_current_user, get_db, register_lifecycle_callbacks
from iot_core import RegistrationNotFound
from iot_core.models import LifecycleEvent
from iot_core import protocol as p
from test_app import http
from test_gateway import online_device


@pytest.fixture
async def lifecycle_app(tmp_path, gateway, monkeypatch):
    import app.main as main

    engine = create_engine(f"sqlite:///{tmp_path / 'lifecycle.db'}",
                           connect_args={"check_same_thread": False})
    tables = [models.User, models.Barn, models.BarnAssignment, models.Device, models.DeviceEvent]
    Base.metadata.create_all(engine, tables=[model.__table__ for model in tables])
    with engine.begin() as connection:
        connection.exec_driver_sql("""CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id VARCHAR(36),
            action VARCHAR(100), target VARCHAR(255), result VARCHAR(100), ts DATETIME)""")
    factory = sessionmaker(bind=engine, autoflush=False)
    device_id = await online_device(gateway)
    with factory() as db:
        db.add_all([models.Barn(id="barn-1", name="One"), models.Barn(id="barn-2", name="Two")])
        for key, role in [("admin", "Admin"), ("operator", "Operator"), ("viewer", "Viewer")]:
            db.add(models.User(id=key, username=key, role=role, password_hash="unused"))
        db.flush()
        db.add_all([
            models.Device(device_id=device_id, hw_id="aabbccddeeff", barn_id="barn-1"),
            models.Device(device_id="other-barn", hw_id="other-hw", barn_id="barn-2"),
            models.Device(device_id="unassigned", hw_id="unassigned-hw"),
            models.BarnAssignment(barn_id="barn-1", user_id="operator", access_level="Operator"),
            models.BarnAssignment(barn_id="barn-1", user_id="viewer", access_level="Viewer"),
        ])
        db.commit()

    actor = SimpleNamespace(id="admin", role="Admin")
    previous = app.dependency_overrides.copy()

    def session():
        with factory() as db:
            yield db

    monkeypatch.setattr(main, "SessionLocal", factory)
    app.state.gateway = gateway
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = lambda: actor
    register_lifecycle_callbacks(app)
    try:
        yield SimpleNamespace(gateway=gateway, db=factory, actor=actor, device_id=device_id)
    finally:
        for unsubscribe in app.state.lifecycle_unsubscribes:
            unsubscribe()
        app.state.lifecycle_gateway = None
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        engine.dispose()


async def test_lifecycle_routes_audit_and_event_history(lifecycle_app):
    ctx = lifecycle_app
    base = f"/devices/{ctx.device_id}"
    steps = [
        ("maintenance", {"on": True, "reason": "Thay cảm biến"}, "maintenance"),
        ("maintenance", {"on": False}, "active"),
        ("suspend", {"reason": "Kiểm tra"}, "suspended"),
        ("resume", None, "active"),
        ("decommission", {"reason": "Hết sử dụng"}, "decommissioned"),
    ]
    for action, body, expected in steps:
        status, row = await http(ctx.gateway, "POST", f"{base}/{action}", body)
        assert status == 200 and row["lifecycle"] == expected
        if expected in {"maintenance", "suspended", "decommissioned"}:
            status, registrations = await http(ctx.gateway, "GET", "/registrations",
                                               query=f"status={expected}".encode())
            assert status == 200 and len(registrations) == 1
            assert registrations[0]["status"] == expected
            assert "password" not in registrations[0] and "password_hash" not in registrations[0]

    status, history = await http(ctx.gateway, "GET", f"{base}/events")
    assert status == 200 and len(history) == 5
    assert [row["detail"]["state"] for row in history] == [step[2] for step in reversed(steps)]
    assert history[0]["detail"]["reason"] == "Hết sử dụng"
    assert history[-1]["detail"]["reason"] == "Thay cảm biến"
    assert all(row["type"] == "lifecycle" and row["ts"] for row in history)
    assert all(row["device_id"] == ctx.device_id for row in history)
    assert (await http(ctx.gateway, "GET", f"{base}/events", query=b"limit=1"))[1] == history[:1]
    assert (await http(ctx.gateway, "GET", f"{base}/events", query=b"limit=0"))[0] == 422

    status, row = await http(ctx.gateway, "POST", "/registrations/aabbccddeeff/recommission")
    assert status == 200 and row["status"] == "revoked" and row["reason"] is None
    assert "password" not in row and "password_hash" not in row
    with ctx.db() as db:
        logs = db.query(models.AuditLog).order_by(models.AuditLog.id).all()
        assert [row.action for row in logs] == [
            "device.maintenance", "device.resume", "device.suspend", "device.resume",
            "device.decommission", "registration.recommission",
        ]
        assert [row.target for row in logs] == [f"devices:{ctx.device_id}"] * 5 + [
            "registrations:aabbccddeeff"]
        assert all(row.user_id == "admin" and row.result == "success" for row in logs)


@pytest.mark.parametrize("role", ["Operator", "Viewer"])
@pytest.mark.parametrize("path,body", [
    ("maintenance", {"on": True}), ("maintenance", {"on": False}),
    ("suspend", {}), ("resume", None), ("decommission", {}), ("recommission", None),
])
async def test_only_admin_may_change_lifecycle(lifecycle_app, role, path, body):
    ctx = lifecycle_app
    ctx.actor.id, ctx.actor.role = role.lower(), role
    url = ("/registrations/aabbccddeeff/recommission" if path == "recommission"
           else f"/devices/{ctx.device_id}/{path}")
    assert (await http(ctx.gateway, "POST", url, body))[0] == 403
    assert (await ctx.gateway.get_device(ctx.device_id)).lifecycle == "active"
    with ctx.db() as db:
        assert db.query(models.AuditLog).count() == db.query(models.DeviceEvent).count() == 0


async def test_invalid_transitions_return_409_without_audit(lifecycle_app):
    ctx = lifecycle_app
    base = f"/devices/{ctx.device_id}"
    for path, body in [(f"{base}/resume", None), (f"{base}/maintenance", {"on": False}),
                       ("/registrations/aabbccddeeff/recommission", None)]:
        assert (await http(ctx.gateway, "POST", path, body))[0] == 409
    assert (await http(ctx.gateway, "POST", f"{base}/suspend"))[0] == 200
    for path, body in [("suspend", {}), ("maintenance", {"on": True})]:
        assert (await http(ctx.gateway, "POST", f"{base}/{path}", body))[0] == 409
    assert (await http(ctx.gateway, "POST", f"{base}/decommission"))[0] == 200
    for path, body in [("resume", None), ("suspend", {}), ("maintenance", {"on": True}),
                       ("decommission", {})]:
        assert (await http(ctx.gateway, "POST", f"{base}/{path}", body))[0] == 409
    with ctx.db() as db:
        assert db.query(models.AuditLog).count() == db.query(models.DeviceEvent).count() == 2


@pytest.mark.parametrize("path,body", [
    ("/devices/missing/maintenance", {"on": True}),
    ("/devices/missing/maintenance", {"on": False}),
    ("/devices/missing/suspend", {}), ("/devices/missing/resume", None),
    ("/devices/missing/decommission", {}), ("/registrations/missing/recommission", None),
])
async def test_missing_lifecycle_targets_return_404(lifecycle_app, path, body):
    ctx = lifecycle_app
    assert (await http(ctx.gateway, "POST", path, body))[0] == 404
    with ctx.db() as db:
        assert db.query(models.AuditLog).count() == 0


async def test_missing_registration_is_mapped_on_device_route(lifecycle_app, monkeypatch):
    async def missing(*args):
        raise RegistrationNotFound("missing-hw")

    ctx = lifecycle_app
    monkeypatch.setattr(ctx.gateway, "set_maintenance", missing)
    assert (await http(ctx.gateway, "POST", f"/devices/{ctx.device_id}/maintenance", {"on": True}))[0] == 404


@pytest.mark.parametrize("body", [{}, {"on": "false"}, {"on": 0}, {"on": None}])
async def test_maintenance_requires_boolean_on(lifecycle_app, body):
    ctx = lifecycle_app
    assert (await http(ctx.gateway, "POST", f"/devices/{ctx.device_id}/maintenance", body))[0] == 422
    with ctx.db() as db:
        assert db.query(models.AuditLog).count() == 0


@pytest.mark.parametrize("role", ["Admin", "Operator", "Viewer"])
async def test_device_events_follow_barn_read_access(lifecycle_app, role):
    ctx = lifecycle_app
    await ctx.gateway.set_maintenance(ctx.device_id)
    # A different device's events must never leak into this device's history.
    await ctx.gateway._emit("lifecycle", LifecycleEvent("other-barn", "fault", "room",
                                                       datetime.now(timezone.utc)))
    ctx.actor.id, ctx.actor.role = role.lower(), role
    status, rows = await http(ctx.gateway, "GET", f"/devices/{ctx.device_id}/events")
    assert status == 200 and len(rows) == 1 and rows[0]["detail"]["state"] == "maintenance"
    for device_id in ["other-barn", "unassigned"]:
        assert (await http(ctx.gateway, "GET", f"/devices/{device_id}/events"))[0] == (
            200 if role == "Admin" else 403)
    assert (await http(ctx.gateway, "GET", "/devices/missing/events"))[0] == 404


async def test_lifespan_records_once_in_worker_and_unsubscribes(lifecycle_app, monkeypatch):
    import app.main as main

    ctx = lifecycle_app
    worker_threads = []

    def inserted(*args):
        worker_threads.append(get_ident())

    @asynccontextmanager
    async def configured_gateway(*args, **kwargs):
        yield ctx.gateway

    monkeypatch.setattr(main, "DATABASE_URL", None)
    monkeypatch.setattr(main, "test_db_connection", lambda: True)
    monkeypatch.setattr(main.GatewayConfig, "from_env", lambda _: None)
    monkeypatch.setattr(main.DeviceGateway, "from_config", configured_gateway)
    event.listen(models.DeviceEvent, "before_insert", inserted)
    try:
        async with main.lifespan(app):
            register_lifecycle_callbacks(app)
            assert len(ctx.gateway._events["lifecycle"]) == 1
            await ctx.gateway.set_maintenance(ctx.device_id, "Inspection")
            assert worker_threads and all(thread != get_ident() for thread in worker_threads)
            with ctx.db() as db:
                assert db.query(models.DeviceEvent).count() == 1
        assert not ctx.gateway._events["lifecycle"]
        await ctx.gateway.resume(ctx.device_id)
        with ctx.db() as db:
            assert db.query(models.DeviceEvent).count() == 1
    finally:
        event.remove(models.DeviceEvent, "before_insert", inserted)


async def test_sensor_fault_and_recovery_are_persisted(lifecycle_app):
    ctx = lifecycle_app
    for errors in [{"room": "timeout"}, {"room": "timeout"}, {}]:
        await ctx.gateway._message(p.device_topic(ctx.device_id, p.TELEMETRY),
            p.Envelope(p.TELEMETRY, {"readings": {}, "errors": errors}).encode())
    status, history = await http(ctx.gateway, "GET", f"/devices/{ctx.device_id}/events")
    assert status == 200
    assert [row["detail"] for row in history] == [
        {"state": "active", "reason": None}, {"state": "fault", "reason": "room"},
    ]
    with ctx.db() as db:
        assert db.query(models.AuditLog).count() == 0
