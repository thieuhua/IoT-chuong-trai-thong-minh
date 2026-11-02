from __future__ import annotations

from datetime import datetime, timedelta, timezone

from iot_core import Device, Readings, Registration, RegistrationStatus, SensorSpec, TelemetryRecord
from iot_core.registry import SqliteDeviceRegistry
from iot_core.telemetry import SqliteTelemetryStore


async def test_registry_roundtrip(tmp_path):
    path = tmp_path / 'nested/db.sqlite'
    registry = SqliteDeviceRegistry(path)
    await registry.open()
    now = datetime.now(timezone.utc)
    device = Device('test-device', 'abcd', sensors=[SensorSpec('room', 'dht', {'temperature': '°C'})],
                    commands=['read'], registered_at=now)
    registration = Registration('abcd', RegistrationStatus.PENDING, now, now, password='a' * 32)
    await registry.save_device(device)
    await registry.save_registration(registration)
    assert await registry.get_device('test-device') == device
    assert await registry.get_device_by_hw_id('abcd') == device
    assert await registry.get_registration('abcd') == registration
    assert await registry.list_registrations(RegistrationStatus.APPROVED) == []
    await registry.touch('test-device', now, True)
    assert (await registry.list_devices())[0].online
    await registry.close()
    await registry.open()
    assert (await registry.get_device('test-device')).last_seen == now
    await registry.delete_device('test-device')
    assert await registry.get_device('test-device') is None
    await registry.close()


async def test_telemetry_trim_history_and_delete(tmp_path):
    store = SqliteTelemetryStore(tmp_path / 'db', keep_per_device=3)
    await store.open()
    now = datetime.now(timezone.utc)
    for i in range(5):
        await store.append(TelemetryRecord('abc', now + timedelta(seconds=i), i, Readings({'room': {'t': i}}, {'soil': 'timeout'})))
    await store.append(TelemetryRecord('other', now, None, Readings()))
    assert [r.device_ts for r in await store.history('abc')] == [4, 3, 2]
    assert (await store.latest('abc')).readings.values == {'room': {'t': 4}}
    assert len(await store.history('abc', since=now + timedelta(seconds=3))) == 2
    await store.delete_device('abc')
    assert await store.latest('abc') is None
    assert await store.latest('other') is not None
    await store.close()
