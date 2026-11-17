import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import models
from app.main import app, get_current_user, get_db
from test_app import http


class PermissionQuery:
    def __init__(self, result):
        self.result = result

    def filter(self, *args):
        return self

    def first(self):
        if isinstance(self.result, list):
            return self.result[0] if self.result else None
        return self.result

    def all(self):
        return self.result if isinstance(self.result, list) else [self.result]

    def order_by(self, *args):
        return self


class PermissionDB:
    def __init__(self):
        self.device = SimpleNamespace(barn_id="barn-1")
        self.barns = [
            SimpleNamespace(id="barn-1", name="Barn 1", zone=None, animal_type=None),
            SimpleNamespace(id="barn-2", name="Barn 2", zone=None, animal_type=None),
        ]
        self.event = SimpleNamespace(
            id="event-1",
            barn_id="barn-1",
            device_id="dev",
            command_name="relay_set",
            args=None,
            run_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
            duration_seconds=10,
            status="pending",
            error=None,
            executed_at=None,
            created_at=None,
            repeat_type="once",
        )

    def query(self, model):
        if model is models.Device:
            return PermissionQuery(self.device)
        if model is models.ScheduledEvent:
            return PermissionQuery(self.event)
        if model is models.Barn:
            return PermissionQuery(self.barns)
        raise AssertionError(f"Unexpected model: {model}")

    def add(self, entity):
        if isinstance(entity, models.ScheduledEvent):
            entity.id = "event-2"
            self.event = entity

    def commit(self):
        pass

    def flush(self):
        pass

    def refresh(self, event):
        pass

    def rollback(self):
        pass


@pytest.fixture
def user_access():
    previous_overrides = app.dependency_overrides.copy()
    current_user = SimpleNamespace(id="test-user", role="Operator")
    db = PermissionDB()
    app.dependency_overrides[get_current_user] = lambda: current_user
    app.dependency_overrides[get_db] = lambda: db
    yield current_user
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous_overrides)


async def test_viewer_cannot_send_commands_reboot_or_start_ota(gateway, user_access):
    user_access.role = "Viewer"
    assert (await http(gateway, "POST", "/devices/dev/commands", {"name": "relay_set"}))[0] == 403
    assert (await http(gateway, "POST", "/devices/dev/reboot"))[0] == 403
    assert (await http(
        gateway,
        "POST",
        "/devices/dev/firmware",
        {"version": "v1", "files": {"app.py": "YWJj"}},
    ))[0] == 403
    schedule = {
        "device_id": "dev",
        "command_name": "relay_set",
        "run_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    assert (await http(
        gateway, "POST", "/barns/barn-1/scheduled-events", schedule
    ))[0] == 403
    assert (await http(gateway, "DELETE", "/scheduled-events/event-1"))[0] == 403
    assert (await http(
        gateway, "GET", "/barns/barn-1/scheduled-events"
    ))[0] == 200
    status, barns = await http(gateway, "GET", "/barns")
    assert status == 200 and [barn["id"] for barn in barns] == ["barn-1", "barn-2"]


async def test_operator_can_send_commands_reboot_and_start_ota(
    gateway, monkeypatch, user_access
):
    calls = []

    async def send_command(device_id, name, args, timeout_s):
        calls.append(("command", device_id, name))
        return {"ok": True}

    async def reboot(device_id):
        calls.append(("reboot", device_id))

    async def update_firmware(device_id, files, version, *, on_progress, wait_confirm):
        calls.append(("firmware", device_id, version))
        return {"state": "confirmed"}

    monkeypatch.setattr(gateway, "send_command", send_command)
    monkeypatch.setattr(gateway, "reboot", reboot)
    monkeypatch.setattr(gateway, "update_firmware", update_firmware)

    assert await http(gateway, "POST", "/devices/dev/commands", {"name": "relay_set"}) == (
        200, {"ok": True}
    )
    assert await http(gateway, "POST", "/devices/dev/reboot") == (200, {"ok": True})

    status, job = await http(
        gateway,
        "POST",
        "/devices/dev/firmware",
        {"version": "v1", "files": {"app.py": "YWJj"}},
    )
    assert status == 202
    await asyncio.gather(*app.state.firmware_tasks)
    assert app.state.firmware_jobs[job["job_id"]]["state"] == "succeeded"
    assert calls == [
        ("command", "dev", "relay_set"),
        ("reboot", "dev"),
        ("firmware", "dev", "v1"),
    ]
    schedule = {
        "device_id": "dev",
        "command_name": "relay_set",
        "run_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    status, created = await http(
        gateway, "POST", "/barns/barn-1/scheduled-events", schedule
    )
    assert status == 201 and created["id"] == "event-2"
    status, cancelled = await http(
        gateway, "DELETE", "/scheduled-events/event-2"
    )
    assert status == 200 and cancelled["event_id"] == "event-2"
