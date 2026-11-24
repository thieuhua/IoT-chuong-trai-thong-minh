"""Series API against real SQL tables, including permissions and sparse data."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.main import app, ensure_gateway_callbacks, get_current_user, get_db
from test_app import _http


START = datetime(2026, 11, 20, tzinfo=timezone.utc)


@pytest.fixture
def series_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'series.db'}",
                           connect_args={"check_same_thread": False})
    tables = [models.User, models.Barn, models.BarnAssignment, models.Device, models.Telemetry]
    Base.metadata.create_all(engine, tables=[model.__table__ for model in tables])
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all([
            models.User(id="viewer", username="viewer", role="Viewer", password_hash="unused"),
            models.Barn(id="barn-1", name="One"), models.Barn(id="barn-2", name="Two"),
            models.BarnAssignment(barn_id="barn-1", user_id="viewer", access_level="Viewer"),
            models.Device(device_id="dev", hw_id="hw-1", barn_id="barn-1"),
            models.Device(device_id="other", hw_id="hw-2", barn_id="barn-2"),
            models.Device(device_id="unassigned", hw_id="hw-3"),
        ])
        db.commit()
    yield factory
    engine.dispose()


@pytest.fixture
def series_access(series_db):
    saved = app.dependency_overrides.copy()
    user = SimpleNamespace(id="viewer", role="Viewer")

    def session():
        with series_db() as db:
            yield db

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = lambda: user
    yield user
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


def add_rows(factory, samples):
    """Samples: (seconds after START, readings, device). IDs explicit for SQLite BigInteger."""
    with factory() as db:
        db.add_all([
            models.Telemetry(id=i + 1, device_id=device,
                             received_at=(START + timedelta(seconds=seconds)).replace(tzinfo=None),
                             readings=readings)
            for i, (seconds, readings, device) in enumerate(samples)
        ])
        db.commit()


async def series(device="dev", **params):
    return await _http("GET", f"/devices/{device}/telemetry/series", None,
                       urlencode(params).encode())


async def test_statistics_are_per_sensor_field_and_bounds_filter_rows(series_db, series_access):
    add_rows(series_db, [
        (-1, {"values": {"room": {"temperature": -999}}}, "dev"),
        (0, {"values": {"room": {"temperature": 20, "humidity": 50, "ok": True}}}, "dev"),
        (10, {"values": {"room": {"temperature": 24, "humidity": None, "note": "25"},
                         "yard": {"temperature": 12, "pressure": 1000}}}, "dev"),
        (29.999999, {"values": {"room": {"temperature": 22}}}, "dev"),
        (30, {"values": {"room": {"temperature": 26, "humidity": 60}}}, "dev"),
        (59, {"values": {"room": {"temperature": 28, "humidity": 64}}}, "dev"),
        (60, {"values": {"room": {"temperature": 999}}}, "dev"),
        (0, {"values": {"room": {"temperature": 999}}}, "other"),
    ])
    status, data = await series(since=START.isoformat(), until=(START + timedelta(minutes=1)).isoformat(), points=2)
    assert status == 200
    assert data["device_id"] == "dev" and data["bucket_s"] == 30
    first, second = data["buckets"]
    assert datetime.fromisoformat(first["time"]) == START
    assert datetime.fromisoformat(second["time"]) == START + timedelta(seconds=30)
    assert first["readings"] == {
        "room": {"temperature": {"avg": 22, "min": 20, "max": 24, "count": 3},
                 "humidity": {"avg": 50, "min": 50, "max": 50, "count": 1}},
        "yard": {"temperature": {"avg": 12, "min": 12, "max": 12, "count": 1},
                 "pressure": {"avg": 1000, "min": 1000, "max": 1000, "count": 1}},
    }
    assert second["readings"]["room"] == {
        "temperature": {"avg": 27, "min": 26, "max": 28, "count": 2},
        "humidity": {"avg": 62, "min": 60, "max": 64, "count": 2},
    }


async def test_sparse_buckets_and_invalid_fields_remain_gaps(series_db, series_access):
    add_rows(series_db, [
        (0, {"values": {"room": {"temp": 30, "hum": 70}}}, "dev"),
        (25, {"values": {"room": {"temp": None, "hum": "broken", "ok": False,
                                   "nan": float("nan"), "inf": float("inf")},
                         "bad": [], "missing": None}, "errors": {"room": "timeout"}}, "dev"),
        (35, {"values": None}, "dev"),
        (45, {"room": {"temp": 32}}, "dev"),  # Legacy unwrapped readings.
    ])
    status, data = await series(since=START.isoformat(), until=(START + timedelta(seconds=50)).isoformat(), points=5)
    assert status == 200
    assert len(data["buckets"]) == 5
    assert [bucket["readings"] for bucket in data["buckets"]][1:4] == [{}, {}, {}]
    assert data["buckets"][-1]["readings"]["room"]["temp"]["avg"] == 32


async def test_streams_all_samples_with_bounded_output_and_column_projection(series_db, series_access):
    add_rows(series_db, [(i / 25, {"values": {"room": {"temp": i}}}, "dev") for i in range(1500)])
    queries = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT telemetry."):
            queries.append(statement)

    engine = series_db.kw["bind"]
    event.listen(engine, "before_cursor_execute", capture)
    try:
        status, data = await series(since=START.isoformat(), until=(START + timedelta(seconds=61)).isoformat(), points=7)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert status == 200
    assert len(data["buckets"]) == 7 and data["bucket_s"] == 9
    stats = [b["readings"]["room"]["temp"] for b in data["buckets"]]
    assert sum(s["count"] for s in stats) == 1500
    assert sum(s["avg"] * s["count"] for s in stats) / 1500 == pytest.approx(749.5)
    assert min(s["min"] for s in stats) == 0 and max(s["max"] for s in stats) == 1499
    assert len(queries) == 1
    projection, filters = queries[0].split("FROM telemetry")
    assert "telemetry.received_at" in projection and "telemetry.readings" in projection
    assert "telemetry.id" not in projection and "telemetry.device_ts" not in projection
    assert "telemetry.device_id =" in filters
    assert "telemetry.received_at >=" in filters and "telemetry.received_at <" in filters


async def test_default_window_is_last_day_and_empty_data_is_valid(series_access):
    before = datetime.now(timezone.utc)
    status, data = await series()
    after = datetime.now(timezone.utc)
    assert status == 200
    until = datetime.fromisoformat(data["until"])
    since = datetime.fromisoformat(data["since"])
    assert before <= until <= after and until - since == timedelta(hours=24)
    assert data["bucket_s"] == 144 and len(data["buckets"]) == 600
    assert all(bucket["readings"] == {} for bucket in data["buckets"])


async def test_offsets_naive_inputs_and_subsecond_window(series_db, series_access):
    add_rows(series_db, [(0.1, {"values": {"room": {"temp": 21}}}, "dev")])
    status, data = await series(since="2026-11-20T07:00:00+07:00", until="2026-11-20T00:00:00.5", points=600)
    assert status == 200
    assert datetime.fromisoformat(data["since"]) == START
    assert data["bucket_s"] == 1 and len(data["buckets"]) == 1
    assert data["buckets"][0]["readings"]["room"]["temp"]["count"] == 1
    status, data = await series(until="2026-11-20T07:00:00+07:00", points=1)
    assert status == 200
    assert datetime.fromisoformat(data["until"]) == START
    assert datetime.fromisoformat(data["since"]) == START - timedelta(days=1)


@pytest.mark.parametrize("params", [
    {"points": 0}, {"points": -1}, {"points": 2001}, {"points": "many"},
    {"since": "bad"}, {"until": "bad"},
    {"since": START.isoformat(), "until": START.isoformat()},
    {"since": (START + timedelta(days=1)).isoformat(), "until": START.isoformat()},
])
async def test_invalid_query_is_422(series_access, params):
    assert (await series(**params))[0] == 422


async def test_device_read_permissions_and_missing_device(series_access):
    assert (await series())[0] == 200  # Viewer assigned to this barn.
    assert (await series("other"))[0] == 403
    assert (await series("unassigned"))[0] == 403
    assert (await series("missing"))[0] == 404
    series_access.role = "Admin"
    assert (await series("other"))[0] == 200
    assert (await series("unassigned"))[0] == 200
    del app.dependency_overrides[get_current_user]
    app.dependency_overrides[ensure_gateway_callbacks] = lambda: None
    assert (await series())[0] == 401
