"""Hệ thống chạy trọn trong một tiến trình để test: API FastAPI + DeviceGateway +
lưu trữ SQLAlchemy (MySQLDeviceRegistry/MySQLTelemetryStore, chạy trên SQLite) +
broker MQTT trong bộ nhớ có Dynamic Security + ESP32 ảo chạy code firmware.

Không cần Docker, MySQL hay ESP32. Test với Mosquitto thật nằm trong
`test_09_broker_that.py` và tự bỏ qua khi không có broker.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import platform
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent

# Phải đặt trước khi import backend: không đọc deployment/.env thật của máy đang chạy.
os.environ["IOT_ENV_FILE"] = str(TESTS / "khong-co-file.env")
os.environ.pop("DATABASE_URL", None)
os.environ.setdefault("JWT_SECRET_KEY", "khoa-bi-mat-chi-dung-cho-test-" + "x" * 32)
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(TESTS))

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import BigInteger, create_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402


@compiles(BigInteger, "sqlite")
def _bigint_sqlite(type_, compiler, **kw):
    # SQLite chỉ tự tăng khóa chính kiểu INTEGER; MySQL vẫn dùng BIGINT.
    return "INTEGER"


from app import database, models  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.services import auth  # noqa: E402
from app.storage_mysql import MySQLDeviceRegistry, MySQLTelemetryStore  # noqa: E402
from iot_core import AuthMode, DeviceGateway, GatewayConfig  # noqa: E402
from iot_core.broker_auth import DynSecAuth  # noqa: E402

from support.broker import BrokerTransport, InMemoryBroker  # noqa: E402
from support.device import FirmwareDevice  # noqa: E402

PASSWORD = "MatKhau@123"
_HASH: str | None = None


def password_hash() -> str:
    global _HASH  # bcrypt cố ý chậm (~0,2 s): băm một lần cho cả phiên test
    if _HASH is None:
        _HASH = auth.hash_password(PASSWORD)
    return _HASH


def token_for(user_id: str, minutes: int = 30, token_type: str = "access") -> str:
    return auth.create_token(user_id, token_type, timedelta(minutes=minutes))[0]


# ---------------------------------------------------------------------------
# Cơ sở dữ liệu
# ---------------------------------------------------------------------------
@pytest.fixture
def engine(tmp_path):
    # Pool mặc định của SQLAlchemy giống backend thật (5 + 10 kết nối); chờ tối đa 5 s
    # thay vì 30 s để test về nghẽn pool (TC-87) chạy nhanh.
    eng = create_engine(f"sqlite:///{tmp_path / 'iot-test.db'}",
                        connect_args={"check_same_thread": False}, pool_timeout=5)
    database.Base.metadata.create_all(eng)
    previous = database.SessionLocal.kw.get("bind")
    database.SessionLocal.configure(bind=eng)  # storage_mysql + scheduler dùng SessionLocal
    yield eng
    database.SessionLocal.configure(bind=previous)
    eng.dispose()


@pytest.fixture
def db(engine):
    with Session(engine) as session:
        yield session


# ---------------------------------------------------------------------------
# Hệ thống đầy đủ
# ---------------------------------------------------------------------------
class System:
    """Một "bản cài" hoàn chỉnh: 3 người dùng (Admin/Operator/Viewer), 2 chuồng."""

    def __init__(self, broker, gateway, client, engine, tmp_path):
        self.broker, self.gateway, self.client = broker, gateway, client
        self.engine, self.tmp_path = engine, tmp_path
        self.users: dict[str, str] = {}
        self.tokens: dict[str, str] = {}
        self.devices: list[FirmwareDevice] = []

    def db(self) -> Session:
        return Session(self.engine)

    def headers(self, who: str) -> dict:
        return {"Authorization": f"Bearer {self.tokens[who]}"}

    async def call(self, who: str | None, method: str, path: str, **kwargs) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        if who is not None:
            headers = {**self.headers(who), **headers}
        return await self.client.request(method, path, headers=headers, **kwargs)

    def add_user(self, key: str, role: str, status: str = "active") -> str:
        user_id = str(uuid.uuid4())
        with self.db() as session:
            session.add(models.User(id=user_id, username=key, password_hash=password_hash(),
                                    full_name=key.title(), role=role, status=status))
            session.commit()
        self.users[key] = user_id
        self.tokens[key] = token_for(user_id)
        return user_id

    def add_barn(self, barn_id: str, name: str) -> None:
        with self.db() as session:
            session.add(models.Barn(id=barn_id, name=name, zone="A", animal_type="gà"))
            session.commit()

    def assign(self, barn_id: str, key: str, level: str) -> None:
        with self.db() as session:
            session.add(models.BarnAssignment(user_id=self.users[key], barn_id=barn_id, access_level=level))
            session.commit()

    def new_device(self, **kwargs) -> FirmwareDevice:
        index = len(self.devices)
        device = FirmwareDevice(self.broker, self.tmp_path / f"esp32-{index}", **kwargs)
        self.devices.append(device)
        return device

    async def approve_via_api(self, hw_id: str) -> None:
        response = await self.call("admin", "POST", f"/registrations/{hw_id}/approve", json={})
        assert response.status_code == 200, response.text

    async def online_device(self, barn_id: str | None = "barn-1", **kwargs) -> FirmwareDevice:
        """ESP32 ảo đã được admin duyệt, đang online, đã gán vào chuồng."""
        device = self.new_device(**kwargs)
        await device.provision_and_connect(self.approve_via_api)
        if barn_id is not None:
            response = await self.call("admin", "PUT", f"/devices/{device.device_id}/barn",
                                       json={"barn_id": barn_id})
            assert response.status_code == 200, response.text
        return device

    def audit_actions(self) -> list[str]:
        with self.db() as session:
            return [row.action for row in session.query(models.AuditLog).order_by(models.AuditLog.id)]


@pytest.fixture
def broker():
    return InMemoryBroker()


@pytest.fixture
async def system(engine, broker, tmp_path):
    transport = BrokerTransport(broker)
    config = GatewayConfig(auth_mode=AuthMode.DYNSEC, command_timeout_s=2.0,
                           bootstrap_password="bootstrap-pw")
    gateway = DeviceGateway(config, transport=transport, registry=MySQLDeviceRegistry(),
                            telemetry=MySQLTelemetryStore(), broker_auth=DynSecAuth(transport))
    async with gateway:
        fastapi_app.state.gateway = gateway
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fastapi_app),
                                     base_url="http://test") as client:
            s = System(broker, gateway, client, engine, tmp_path)
            s.add_user("admin", "Admin")
            s.add_user("operator", "Operator")
            s.add_user("viewer", "Viewer")
            s.add_user("operator2", "Operator")  # Operator của chuồng khác
            s.add_barn("barn-1", "Chuồng gà 1")
            s.add_barn("barn-2", "Chuồng gà 2")
            s.assign("barn-1", "operator", "Operator")
            s.assign("barn-1", "viewer", "Viewer")
            s.assign("barn-2", "operator2", "Operator")
            yield s
            await broker.settle()
    await transport.close()


# ---------------------------------------------------------------------------
# Số đo cho chương kiểm thử của báo cáo
# ---------------------------------------------------------------------------
MEASUREMENTS: list[dict] = []


@pytest.fixture
def do_luong(request):
    """Ghi một số đo: do_luong("Tên", giá_trị, "đơn vị", nguong="≤ 200 ms", dat=True)."""
    def record(name, value, unit, *, nguong="", dat=None, ghi_chu=""):
        MEASUREMENTS.append(dict(test=request.node.nodeid, name=name, value=value, unit=unit,
                                 nguong=nguong, dat=dat, ghi_chu=ghi_chu))
    return record


def pytest_sessionfinish(session, exitstatus):
    if not MEASUREMENTS:
        return
    out = TESTS / "ket-qua"
    out.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).astimezone()
    env = f"Python {platform.python_version()}, {platform.system()} {platform.machine()}"
    (out / "so-do-moi-nhat.json").write_text(json.dumps(
        {"thoi_gian": now.isoformat(timespec="seconds"), "moi_truong": env, "so_do": MEASUREMENTS},
        ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# Số đo kiểm thử phi chức năng ({now:%d/%m/%Y %H:%M})", "",
             f"Môi trường: {env}. Broker trong bộ nhớ trừ dòng ghi \"broker thật\".", "",
             "| Chỉ số | Kết quả | Ngưỡng | Đạt | Ghi chú |", "| --- | --- | --- | --- | --- |"]
    for m in MEASUREMENTS:
        value = f"{m['value']:.2f}" if isinstance(m["value"], float) else str(m["value"])
        ok = "" if m["dat"] is None else ("✅" if m["dat"] else "❌")
        lines.append(f"| {m['name']} | {value} {m['unit']} | {m['nguong']} | {ok} | {m['ghi_chu']} |")
    (out / "so-do-moi-nhat.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
