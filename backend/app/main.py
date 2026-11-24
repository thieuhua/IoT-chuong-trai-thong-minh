"""FastAPI adapter for DeviceGateway."""
from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import json
import math
import os
import socket
import urllib.parse
from contextlib import asynccontextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from pathlib import Path
from typing import Any, Literal, Optional


from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from vision import CameraStreamer
except ImportError:
    CameraStreamer = None

from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field


from sqlalchemy.orm import Session


from .database import DATABASE_URL, ENV_FILE, SessionLocal, get_db, init_db
from .database import test_db_connection
from .storage_mysql import MySQLDeviceRegistry, MySQLTelemetryStore
from .schemas import (
    UserRegisterSchema,
    LoginSchema,
    ChangePasswordSchema,
    TokenResponse,
    UserResponse,
    UserUpdateSchema,
)
from .services import alert, audit, barn, user, auth, scheduler
from .services import command as command_service
from .services.alert_engine import AlertEngine
from .services.lifecycle_events import LifecycleEventRecorder
from iot_core import (BrokerAuthError, CommandFailed, CommandTimeout, DeviceGateway,
                      DeviceNotFound, DeviceOffline, GatewayConfig, InvalidState,
                      RegistrationNotFound, RegistrationStatus)

from . import models

from . import schemas


def register_alert_callbacks(app: FastAPI):
    """Also supports gateways injected by an ASGI host without lifespan."""
    gateway = app.state.gateway
    if getattr(app.state, "alert_gateway", None) is gateway:
        return
    for unsubscribe in getattr(app.state, "alert_unsubscribes", ()):
        unsubscribe()
    engine = AlertEngine(SessionLocal)
    app.state.alert_engine = engine
    app.state.alert_unsubscribes = [gateway.on_telemetry(engine.on_telemetry),
                                   gateway.on_status_change(engine.on_status_change)]
    app.state.alert_gateway = gateway


def register_lifecycle_callbacks(app: FastAPI):
    gateway = app.state.gateway
    if getattr(app.state, "lifecycle_gateway", None) is gateway:
        return
    for unsubscribe in getattr(app.state, "lifecycle_unsubscribes", ()):
        unsubscribe()
    recorder = LifecycleEventRecorder(SessionLocal)
    app.state.lifecycle_recorder = recorder
    app.state.lifecycle_unsubscribes = [gateway.on_lifecycle_change(recorder.on_lifecycle_change)]
    app.state.lifecycle_gateway = gateway


async def ensure_gateway_callbacks(request: Request):
    register_alert_callbacks(request.app)
    register_lifecycle_callbacks(request.app)


def public(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {key: public(item) for key, item in value.items()
                if key not in {"password", "password_hash"}}
    if isinstance(value, (list, tuple)):
        return [public(item) for item in value]
    return jsonable_encoder(value)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if test_db_connection():
        print("Database is ready.")
    else:
        print("Database is unavailable.")
    env_file = str(ENV_FILE)  # deployment/.env (or IOT_ENV_FILE), shared with app.database
    # MySQL stores when DATABASE_URL is set; otherwise iot_core's default SQLite stores.
    storage = ({"registry": MySQLDeviceRegistry(), "telemetry": MySQLTelemetryStore()}
               if DATABASE_URL else {})
    async with DeviceGateway.from_config(GatewayConfig.from_env(env_file), **storage) as gateway:
        app.state.gateway = gateway
        register_alert_callbacks(app)
        register_lifecycle_callbacks(app)
        app.state.firmware_jobs = {}
        app.state.firmware_tasks = set()
        app.state.ota_listeners = set()
         # Start scheduled event dispatcher (schedules live in MySQL only)
        scheduler_task = asyncio.create_task(
            scheduler.scheduler_loop(app)
        ) if DATABASE_URL else None
        try:
            yield
        finally:
            for unsubscribe in app.state.alert_unsubscribes:
                unsubscribe()
            app.state.alert_gateway = None
            for unsubscribe in app.state.lifecycle_unsubscribes:
                unsubscribe()
            app.state.lifecycle_gateway = None
            # Stop scheduler
            if scheduler_task is not None:
                scheduler_task.cancel()

                await asyncio.gather(
                    scheduler_task,
                    return_exceptions=True
                )
            tasks = list(app.state.firmware_tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(lifespan=lifespan)

cors_origins_env = os.getenv("CORS_ORIGINS", "")
if cors_origins_env:
    allow_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
else:
    allow_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.state.firmware_jobs = {}
app.state.firmware_tasks = set()
app.state.ota_listeners = set()

camera_streamer = CameraStreamer(source=0, allow_person=False, motionless_sec=40.0) if CameraStreamer else None


async def error_response(request: Request, exc: Exception):
    status = 502
    if isinstance(exc, (DeviceNotFound, RegistrationNotFound)):
        status = 404
    elif isinstance(exc, (DeviceOffline, InvalidState)):
        status = 409
    elif isinstance(exc, CommandTimeout):
        status = 504
    elif isinstance(exc, ValueError):
        status = 422
    body = {"code": exc.code, "message": exc.message} if isinstance(exc, CommandFailed) else {"detail": str(exc)}
    return JSONResponse(body, status_code=status)


for error in (DeviceNotFound, RegistrationNotFound, DeviceOffline, InvalidState,
              CommandTimeout, CommandFailed, ValueError, BrokerAuthError):
    app.add_exception_handler(error, error_response)


class RenameBody(BaseModel):
    name: str | None = None
    barn_id: str | None = None


class LifecycleReasonBody(BaseModel):
    reason: str | None = None


class MaintenanceBody(LifecycleReasonBody):
    on: bool = Field(strict=True)


class CommandBody(BaseModel):
    name: str
    args: dict[str, Any] | None = None
    timeout_s: float | None = Field(default=None, gt=0)


class IntervalBody(BaseModel):
    seconds: int = Field(ge=1, le=3600, strict=True)


class ApproveBody(BaseModel):
    device_id: str | None = None
    name: str = ""
    barn_id: str | None = None


class RejectBody(BaseModel):
    reason: str = ""


MAX_FINISHED_JOBS = 100


class FirmwareBody(BaseModel):
    version: str = Field(min_length=1, max_length=40)
    files: dict[str, str] = Field(min_length=1)
    wait_confirm: bool = True


async def run_firmware_job(app: FastAPI, job: dict, files: dict[str, bytes], wait_confirm: bool):
    def progress(event):
        job["progress"] = dict(event)
        value = {**event, "job_id": job["job_id"], "device_id": job["device_id"]}
        for listener in tuple(app.state.ota_listeners):
            listener("ota", value)

    try:
        job["result"] = await app.state.gateway.update_firmware(
            job["device_id"], files, job["version"], on_progress=progress, wait_confirm=wait_confirm)
        job["state"] = "succeeded"
    except asyncio.CancelledError:
        job.update(state="failed", error="Firmware job cancelled on shutdown")
        raise
    except Exception as exc:
        job.update(state="failed", error=str(exc) or type(exc).__name__)
    finally:
        job["finished_at"] = datetime.now(timezone.utc).isoformat()

security = HTTPBearer(auto_error=False)


def _authenticate(db: Session, raw_token: Optional[str]):
    if not raw_token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return auth.get_current_user(db, raw_token)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
    _gateway_callbacks=Depends(ensure_gateway_callbacks),
):
    """Token chỉ nhận qua header Authorization: Bearer."""
    return _authenticate(db, credentials.credentials if credentials else None)


def get_current_user_allow_query(
    token: Optional[str] = Query(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
):
    """Header hoặc ?token=. Chỉ dùng cho route trình duyệt không gửi được header:
    EventSource (/events) và <img> (/camera/feed). Token trong URL dễ lọt vào log,
    nên không mở cho các route khác."""
    return _authenticate(db, credentials.credentials if credentials else token)


def require_roles(*roles):
    def role_checker(
        current_user: models.User = Depends(get_current_user)
    ):
        if current_user.role not in roles:
            raise HTTPException(
                status_code=403,
                detail="Permission denied"
            )

        return current_user

    return role_checker


def check_barn_access(
    barn_id: str,
    current_user: models.User,
    db: Session
):
    if current_user.role == "Admin":
        barn = db.query(models.Barn).filter(models.Barn.id == barn_id).first()
        if barn:
            return True
        raise HTTPException(status_code=404, detail="Barn not found")

    if current_user.role in {"Operator", "Viewer"}:
        assignment = db.query(models.BarnAssignment).filter(
            models.BarnAssignment.barn_id == barn_id,
            models.BarnAssignment.user_id == current_user.id,
            models.BarnAssignment.access_level == current_user.role
        ).first()
        if assignment:
            return True

    raise HTTPException(
        status_code=403,
        detail="Permission denied"
    )


def check_device_write_access(
    device_id: str,
    db: Session,
    current_user: models.User
):
    if current_user.role not in {"Admin", "Operator"}:
        raise HTTPException(
            status_code=403,
            detail="Permission denied"
        )

    device = db.query(
        models.Device
    ).filter(
        models.Device.device_id == device_id
    ).first()

    if not device:
        raise HTTPException(
            status_code=404,
            detail="Device not found"
        )

    if current_user.role == "Admin":
        return device

    if not device.barn_id:
        raise HTTPException(
            status_code=409,
            detail="Device is not assigned to a barn"
        )

    check_barn_access(device.barn_id, current_user, db)

    return device


def check_device_read_access(device_id: str, db: Session, current_user: models.User):
    device = db.query(models.Device).filter(models.Device.device_id == device_id).first()
    if device is None:
        raise HTTPException(404, "Device not found")
    if current_user.role != "Admin":
        if not device.barn_id:
            raise HTTPException(403, "Permission denied")
        check_barn_access(device.barn_id, current_user, db)
    return device


@app.post("/devices/{device_id}/firmware", status_code=202)
async def firmware(
    request: Request,
    device_id: str,
    body: FirmwareBody,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    check_device_write_access(device_id, db, current_user)

    try:
        files = {path: base64.b64decode(data, validate=True) for path, data in body.files.items()}
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(422, "files must contain valid base64") from exc
    state = request.app.state
    if any(job["device_id"] == device_id and job["state"] == "running"
           for job in state.firmware_jobs.values()):
        raise HTTPException(409, "Firmware job already running for this device")
    job_id = uuid4().hex
    job = dict(job_id=job_id, device_id=device_id, version=body.version, state="running",
               progress=None, result=None, error=None, started_at=datetime.now(timezone.utc).isoformat(),
               finished_at=None)
    finished = [key for key, old in state.firmware_jobs.items() if old["state"] != "running"]
    # Leave room for the new job: it will be a finished job too once it ends.
    for key in finished[:max(0, len(finished) - MAX_FINISHED_JOBS + 1)]:
        del state.firmware_jobs[key]  # dicts keep insertion order: oldest finished jobs go first
    state.firmware_jobs[job_id] = job
    task = asyncio.create_task(run_firmware_job(request.app, job, files, body.wait_confirm))
    state.firmware_tasks.add(task)
    task.add_done_callback(state.firmware_tasks.discard)
    return {"job_id": job_id}


@app.get("/firmware-jobs/{job_id}")
async def firmware_job(
    request: Request,
    job_id: str,
    current_user: models.User = Depends(get_current_user)
):
    job = request.app.state.firmware_jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown firmware job")
    return public(job)


@app.get("/health")
async def health(
    request: Request,
    current_user: models.User = Depends(get_current_user)
):
    return {"broker_connected": request.app.state.gateway.transport.connected}


@app.get("/devices")
async def devices(
    request: Request,
    online: bool | None = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.Device)
    if current_user.role != "Admin":
        query = query.join(models.BarnAssignment,
                           models.Device.barn_id == models.BarnAssignment.barn_id).filter(
            models.BarnAssignment.user_id == current_user.id,
            models.BarnAssignment.access_level == current_user.role,
        )
    barns = {row.device_id: row.barn_id for row in query.all()}
    rows = public(await request.app.state.gateway.list_devices(online))
    return [{**row, "barn_id": barns.get(row["device_id"])} for row in rows
            if current_user.role == "Admin" or row["device_id"] in barns]


@app.get("/devices/{device_id}")
async def device(
    request: Request,
    device_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    row = check_device_read_access(device_id, db, current_user)
    return {**public(await request.app.state.gateway.get_device(device_id)), "barn_id": row.barn_id}


@app.patch("/devices/{device_id}")
async def rename(
    request: Request,
    device_id: str,
    body: RenameBody,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    device = check_device_write_access(device_id, db, current_user)
    device_res = None
    if body.name is not None:
        device_res = await request.app.state.gateway.rename(device_id, body.name)
        if device.name != body.name:
            audit.record_change(db, current_user.id, "device.rename", f"devices:{device_id}")
            db.commit()

    if body.barn_id is not None:
        if body.barn_id:
            barn_row = db.query(models.Barn).filter(models.Barn.id == body.barn_id).first()
            if not barn_row:
                raise HTTPException(404, "Barn not found")
        dev_row = db.query(models.Device).filter(models.Device.device_id == device_id).first()
        if dev_row:
            dev_row.barn_id = body.barn_id or None
            audit.record_change(db, current_user.id, "device.assign_barn", f"devices:{device_id}")
            db.commit()

    if device_res is None:
        device_res = await request.app.state.gateway.get_device(device_id)
    return public(device_res)


@app.delete("/devices/{device_id}")
async def revoke(
    request: Request,
    device_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    check_device_write_access(device_id, db, current_user)
    await request.app.state.gateway.revoke(device_id)
    audit.record_change(db, current_user.id, "device.revoke", f"devices:{device_id}")
    db.commit()
    return {"ok": True}


@app.post("/devices/{device_id}/maintenance")
async def maintenance(
    request: Request,
    device_id: str,
    body: MaintenanceBody,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("Admin")),
):
    gateway = request.app.state.gateway
    result = (await gateway.set_maintenance(device_id, body.reason or "") if body.on
              else await gateway.resume(device_id))
    action = "device.maintenance" if body.on else "device.resume"
    audit.record_change(db, current_user.id, action, f"devices:{device_id}")
    db.commit()
    return public(result)


@app.post("/devices/{device_id}/suspend")
async def suspend(
    request: Request,
    device_id: str,
    body: LifecycleReasonBody | None = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("Admin")),
):
    result = await request.app.state.gateway.suspend(device_id, (body.reason or "") if body else "")
    audit.record_change(db, current_user.id, "device.suspend", f"devices:{device_id}")
    db.commit()
    return public(result)


@app.post("/devices/{device_id}/resume")
async def resume(
    request: Request,
    device_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("Admin")),
):
    result = await request.app.state.gateway.resume(device_id)
    audit.record_change(db, current_user.id, "device.resume", f"devices:{device_id}")
    db.commit()
    return public(result)


@app.post("/devices/{device_id}/decommission")
async def decommission(
    request: Request,
    device_id: str,
    body: LifecycleReasonBody | None = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("Admin")),
):
    result = await request.app.state.gateway.decommission(device_id, (body.reason or "") if body else "")
    audit.record_change(db, current_user.id, "device.decommission", f"devices:{device_id}")
    db.commit()
    return public(result)


@app.get("/devices/{device_id}/events", response_model=list[schemas.DeviceEventResponse])
async def device_events(
    device_id: str,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    check_device_read_access(device_id, db, current_user)
    return (db.query(models.DeviceEvent).filter(models.DeviceEvent.device_id == device_id)
            .order_by(models.DeviceEvent.ts.desc(), models.DeviceEvent.id.desc()).limit(limit).all())


@app.get("/devices/{device_id}/readings")
async def readings(
    request: Request,
    device_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    check_device_read_access(device_id, db, current_user)
    return public(await request.app.state.gateway.read_all(device_id))


@app.get("/devices/{device_id}/sensors/{sensor}")
async def sensor(
    request: Request,
    device_id: str,
    sensor: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    check_device_read_access(device_id, db, current_user)
    return await request.app.state.gateway.read_sensor(device_id, sensor)


@app.post("/devices/{device_id}/commands")
async def command(
    request: Request,
    device_id: str,
    body: CommandBody,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    check_device_write_access(device_id, db, current_user)
    _, result = await command_service.execute_command(
        db, request.app.state.gateway, device_id, current_user.id,
        body.name, body.args, body.timeout_s,
    )
    return result


@app.post("/devices/{device_id}/ping")
async def ping(
    request: Request,
    device_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    check_device_write_access(device_id, db, current_user)
    return await request.app.state.gateway.ping(device_id)


@app.post("/devices/{device_id}/reboot")
async def reboot(
    request: Request,
    device_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    check_device_write_access(device_id, db, current_user)
    await request.app.state.gateway.reboot(device_id)
    return {"ok": True}


@app.put("/devices/{device_id}/interval")
async def interval(
    request: Request,
    device_id: str,
    body: IntervalBody,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    device = check_device_write_access(device_id, db, current_user)
    interval_s = await request.app.state.gateway.set_interval(device_id, body.seconds)
    if device.interval_s != interval_s:
        audit.record_change(
            db, current_user.id, "device.interval.update", f"devices:{device_id}"
        )
        db.commit()
    return {"interval_s": interval_s}


@app.get("/devices/{device_id}/telemetry")
async def telemetry(
    request: Request,
    device_id: str,
    limit: int = Query(100, ge=1),
    since: datetime | None = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    check_device_read_access(device_id, db, current_user)
    return public(await request.app.state.gateway.telemetry_history(device_id, limit, since))


@app.get("/devices/{device_id}/telemetry/latest")
async def latest(
    request: Request,
    device_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    check_device_read_access(device_id, db, current_user)
    return public(await request.app.state.gateway.latest_telemetry(device_id))


@app.get("/devices/{device_id}/telemetry/series")
def telemetry_series(
    device_id: str,
    since: datetime | None = None,
    until: datetime | None = None,
    points: int = Query(600, ge=1, le=2000),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Numeric sensor fields in UTC buckets over [since, until).

    Naive input timestamps are interpreted as UTC, matching the MySQL store.
    Empty buckets are retained so clients can distinguish gaps from a flat line.
    """
    check_device_read_access(device_id, db, current_user)

    def utc(value: datetime) -> datetime:
        return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None
                else value.astimezone(timezone.utc))

    until = utc(until) if until is not None else datetime.now(timezone.utc)
    since = utc(since) if since is not None else until - timedelta(hours=24)
    if since >= until:
        raise HTTPException(422, "since must be before until")

    duration_s = (until - since).total_seconds()
    bucket_s = max(1, math.ceil(duration_s / points))
    buckets = [
        {"time": since + timedelta(seconds=i * bucket_s), "readings": {}}
        for i in range(math.ceil(duration_s / bucket_s))
    ]

    # The store writes UTC without tzinfo to received_at and serializes Readings
    # as {values: {sensor: {field: value}}, errors: {...}}. Use the device/time
    # index, project only these columns and stream rather than loading ORM rows.
    rows = (
        db.query(models.Telemetry.received_at, models.Telemetry.readings)
        .filter(
            models.Telemetry.device_id == device_id,
            models.Telemetry.received_at >= since.replace(tzinfo=None),
            models.Telemetry.received_at < until.replace(tzinfo=None),
        )
        .order_by(models.Telemetry.received_at)
        .yield_per(1000)
    )
    for received_at, readings in rows:
        index = int((utc(received_at) - since).total_seconds() // bucket_s)
        values = readings.get("values", readings) if isinstance(readings, dict) else {}
        if not isinstance(values, dict):
            continue
        for sensor, fields in values.items():
            if not isinstance(fields, dict) or sensor == "errors":
                continue
            for field, value in fields.items():
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value)):
                    continue
                sensor_fields = buckets[index]["readings"].setdefault(sensor, {})
                stats = sensor_fields.get(field)
                if stats is None:
                    sensor_fields[field] = {"avg": value, "min": value, "max": value, "count": 1}
                else:
                    stats["count"] += 1
                    count = stats["count"]
                    stats["avg"] = stats["avg"] * ((count - 1) / count) + value / count
                    stats["min"] = min(stats["min"], value)
                    stats["max"] = max(stats["max"], value)

    return {"device_id": device_id, "since": since, "until": until,
            "bucket_s": bucket_s, "buckets": buckets}


@app.get("/registrations")
async def registrations(
    request: Request,
    status: Literal["pending", "approved", "rejected", "revoked", "maintenance",
                    "suspended", "decommissioned", "all"] = "pending",
    current_user: models.User = Depends(get_current_user)
):
    state = None if status == "all" else RegistrationStatus(status)
    return public(await request.app.state.gateway.list_registrations(state))


@app.post("/registrations/{hw_id}/approve")
async def approve(
    request: Request,
    hw_id: str,
    body: ApproveBody,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("Admin"))
):
    result = await request.app.state.gateway.approve(hw_id, device_id=body.device_id, name=body.name)
    if body.barn_id:
        barn_row = db.query(models.Barn).filter(models.Barn.id == body.barn_id).first()
        if not barn_row:
            raise HTTPException(404, "Barn not found")
        dev_id = getattr(result, "device_id", None) or (result.get("device_id") if isinstance(result, dict) else None)
        if dev_id:
            dev_row = db.query(models.Device).filter(models.Device.device_id == dev_id).first()
            if dev_row:
                dev_row.barn_id = body.barn_id
                db.commit()
    audit.record_change(
        db, current_user.id, "registration.approve", f"registrations:{hw_id}"
    )
    db.commit()
    return public(result)


@app.post("/registrations/{hw_id}/reject")
async def reject(
    request: Request,
    hw_id: str,
    body: RejectBody,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("Admin"))
):
    result = public(await request.app.state.gateway.reject(hw_id, body.reason))
    audit.record_change(
        db, current_user.id, "registration.reject", f"registrations:{hw_id}"
    )
    db.commit()
    return result


@app.post("/registrations/{hw_id}/recommission")
async def recommission(
    request: Request,
    hw_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("Admin")),
):
    result = await request.app.state.gateway.recommission(hw_id)
    audit.record_change(db, current_user.id, "registration.recommission", f"registrations:{hw_id}")
    db.commit()
    return public(result)


@app.get("/events")
async def events(
    request: Request,
    current_user: models.User = Depends(get_current_user_allow_query)
):
    gateway = request.app.state.gateway

    async def stream():
        queue = asyncio.Queue(maxsize=256)

        def enqueue(kind, value):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait((kind, public(value)))

        unsubscribes = [subscribe(lambda value, kind=kind: enqueue(kind, value)) for kind, subscribe in (
            ("telemetry", gateway.on_telemetry), ("status", gateway.on_status_change),
            ("registration", gateway.on_registration), ("device", gateway.on_device_updated))]
        request.app.state.ota_listeners.add(enqueue)
        try:
            while not await request.is_disconnected():
                try:
                    kind, data = await asyncio.wait_for(queue.get(), 15)
                    yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            request.app.state.ota_listeners.discard(enqueue)
            for unsubscribe in unsubscribes:
                unsubscribe()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


#Log in, log out, register account, change password

# =========================================
# WEBSOCKET MANAGER
# =========================================

class ConnectionManager:

    def __init__(self):
        self.connections = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()

        self.connections.setdefault(user_id, []).append(websocket)

    def disconnect(self, websocket: WebSocket, user_id: str):
        connections = self.connections.get(user_id, [])

        if websocket in connections:
            connections.remove(websocket)

        if not connections:
            self.connections.pop(user_id, None)

    async def send_to_user(self, user_id: str, data: dict):
        connections = self.connections.get(user_id, [])

        disconnected = []

        for connection in connections:
            try:
                await connection.send_json(data)
            except Exception:
                disconnected.append(connection)

        for connection in disconnected:
            self.disconnect(connection, user_id)


manager = ConnectionManager()

# =========================================
# 1. AUTHENTICATION ENDPOINTS
# =========================================

@app.post("/auth/login", response_model=schemas.TokenResponse)
def login(
    body: schemas.LoginSchema,
    db: Session = Depends(get_db)
):
    return auth.login(db, body)


@app.post("/auth/refresh")
def refresh_token(
    body: schemas.RefreshTokenSchema,
    db: Session = Depends(get_db)
):
    return auth.refresh_token(db, body)


@app.post("/auth/logout")
def logout(
    body: schemas.RefreshTokenSchema,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return auth.logout(
        db,
        body.refresh_token,
        current_user
    )


@app.put("/me/password")
def change_password(
    body: schemas.ChangePasswordSchema,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return auth.change_password(
        db,
        body,
        current_user
    )

# =========================================
# 2. USER MANAGEMENT
# =========================================

@app.get("/users", response_model=list[schemas.UserResponse])
def get_users(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("Admin"))
):
    return user.get_users(db)


@app.post(
    "/users",
    response_model=schemas.UserResponse,
    status_code=201
)
def create_user(
    body: schemas.UserRegisterSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("Admin"))
):
    return user.create_user(
        db,
        body,
        current_user.id
    )


@app.patch("/users/{user_id}", response_model=schemas.UserResponse)
def update_user(
    user_id: str,
    body: schemas.UserUpdateSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("Admin"))
):
    if user_id == current_user.id and body.status == "locked":
        raise HTTPException(400, "Cannot lock your own account")

    return user.update_user(db, user_id, body, current_user.id)

# =========================================
# 3. BARN MANAGEMENT
# =========================================

@app.get("/barns", response_model=list[schemas.BarnResponse])
def get_barns(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    return barn.get_barns(db, current_user)


@app.post(
    "/barns",
    response_model=schemas.BarnResponse,
    status_code=201
)
def create_barn(
    body: schemas.BarnCreateSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("Admin"))
):
    return barn.create_barn(db, body, current_user.id)


@app.put("/devices/{device_id}/barn")
def update_device_barn(
    device_id: str,
    body: schemas.DeviceBarnUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("Admin"))
):
    device = db.query(models.Device).filter(
        models.Device.device_id == device_id
    ).first()
    if not device:
        raise HTTPException(404, "Device not found")

    if body.barn_id is not None:
        target_barn = db.query(models.Barn).filter(
            models.Barn.id == body.barn_id
        ).first()
        if not target_barn:
            raise HTTPException(404, "Barn not found")

    if device.barn_id == body.barn_id:
        return {"device_id": device_id, "barn_id": device.barn_id}

    try:
        device.barn_id = body.barn_id
        audit.record_change(
            db, current_user.id, "device.barn.update", f"devices:{device_id}"
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {"device_id": device_id, "barn_id": device.barn_id}


@app.put("/barns/{barn_id}/assignments")
def assign_barn(
    barn_id: str,
    body: schemas.BarnAssignmentSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("Admin"))
):
    return barn.assign_users(db, barn_id, body, current_user.id)


@app.delete("/barns/{barn_id}/assignments")
def remove_barn_assignment(
    barn_id: str,
    body: schemas.BarnAssignmentDeleteSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("Admin"))
):
    return barn.remove_user_assignment(
        db,
        barn_id,
        body.user_id,
        current_user.id
    )


@app.get("/barns/{barn_id}/devices", response_model=list[schemas.DeviceResponse])
def get_barn_devices(
    barn_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    check_barn_access(barn_id, current_user, db)
    return barn.get_barn_devices(db, barn_id)


@app.get("/barns/{barn_id}/commands", response_model=list[schemas.CommandResponse])
def get_barn_commands(
    barn_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    check_barn_access(barn_id, current_user, db)
    return command_service.get_commands(db, barn_id)


@app.post("/barns/{barn_id}/commands", response_model=schemas.CommandResponse)
async def send_barn_command(
    request: Request,
    barn_id: str,
    body: schemas.CommandCreateSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("Admin", "Operator")),
):
    check_barn_access(barn_id, current_user, db)
    return await command_service.send_command(
        db, request.app.state.gateway, barn_id, current_user.id, body,
    )


@app.post("/barns/{barn_id}/alert-rules", response_model=schemas.AlertRuleResponse, status_code=201)
def create_alert_rule(
    barn_id: str,
    body: schemas.AlertRuleCreateSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("Admin")),
):
    check_barn_access(barn_id, current_user, db)
    row = models.AlertRule(id=str(uuid4()), barn_id=barn_id, **body.model_dump())
    db.add(row)
    audit.record_change(db, current_user.id, "alert_rule.create", f"alert_rules:{row.id}")
    db.commit()
    db.refresh(row)
    return row


@app.get("/barns/{barn_id}/assignments", response_model=list[schemas.BarnAssignmentResponse])
def get_barn_assignments(
    barn_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    check_barn_access(barn_id, current_user, db)
    return barn.get_barn_assignments(db, barn_id)


@app.get("/barns/{barn_id}/users", response_model=list[schemas.UserResponse])
def get_barn_users(
    barn_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    check_barn_access(barn_id, current_user, db)
    return barn.get_barn_users(db, barn_id)

# =========================================
# 8. ALERTS
# =========================================

@app.get("/alerts", response_model=list[schemas.AlertResponse])
def get_alerts(
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    return alert.get_alerts(
        db,
        current_user,
        status_filter
    )


@app.post("/alerts/{alert_id}/ack")
def acknowledge_alert(
    alert_id: str,
    body: schemas.AlertActionSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(
        require_roles("Admin", "Operator")
    )
):
    return alert.acknowledge_alert(
        db,
        alert_id,
        current_user,
        body.note
    )


@app.post("/alerts/{alert_id}/close")
def close_alert(
    alert_id: str,
    body: schemas.AlertActionSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(
        require_roles("Admin", "Operator")
    )
):
    return alert.close_alert(
        db,
        alert_id,
        current_user,
        body.note
    )
# =========================================
# 9. AUDIT LOGS
# =========================================

@app.get(
    "/audit-logs",
    response_model=list[schemas.AuditLogResponse]
)
def get_audit_logs(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("Admin"))
):
    return audit.get_audit_logs(db)

# =========================================
# 10. WEBSOCKET
# =========================================
def authenticate_websocket(token: str) -> str:
    db = SessionLocal()

    try:
        current_user = auth.get_current_user(db, token)
        return current_user.id

    finally:
        db.close()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    token = websocket.query_params.get("token")

    if not token:
        await websocket.close(code=1008)
        return

    try:
        user_id = await asyncio.to_thread(
            authenticate_websocket,
            token
        )

    except HTTPException:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, user_id)

    try:
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass

    finally:
        manager.disconnect(websocket, user_id)


# =========================================
# 10. Scheduled Events
# =========================================
"""
Body example for creating a turn on relay scheduled event:
{
  "device_id": "_device_id_",
  "command_name": "relay_set",
  "args": {
    "name": "_relay_name_",
    "on": true,
    "duration_ms": 60000
  },
  "run_at": "2026-11-17T12:00:00+07:00",
  "duration_seconds": 10,
  "repeat_type": "once"
}

repeat_type: "once" | "daily" | "weekly" | "monthly"
"""
"""
đến giờ cho ăn, servo quay đến góc 90 độ.
{
  "device_id": "ESP32_001",
  "command_name": "servo_set",
  "args": {
    "name": "feeder",
    "angle": 90
  },
  "run_at": "2026-11-17T12:00:00+07:00",
  "duration_seconds": 10,
  "repeat_type": "once"
}
"""
@app.post(
    "/barns/{barn_id}/scheduled-events",
    status_code=201,
    response_model=schemas.ScheduledEventResponse
)
def create_scheduled_event(
    barn_id: str,
    body: schemas.ScheduledEventCreateSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("Admin", "Operator"))
):
    check_barn_access(
        barn_id,
        current_user,
        db
    )

    device = db.query(models.Device).filter(
        models.Device.device_id == body.device_id,
        models.Device.barn_id == barn_id
    ).first()

    if not device:
        raise HTTPException(
            status_code=404,
            detail="Device not found in this barn"
        )

    # Require timezone-aware datetime.
    if body.run_at.tzinfo is None or body.run_at.utcoffset() is None:
        raise HTTPException(
            status_code=422,
            detail="run_at must include a timezone"
        )

    # Convert to UTC before saving to MySQL.
    run_at = body.run_at.astimezone(
        timezone.utc
    ).replace(tzinfo=None)

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if run_at <= now:
        raise HTTPException(
            status_code=422,
            detail="Scheduled time must be in the future"
        )

    event = models.ScheduledEvent(
        barn_id=barn_id,
        device_id=body.device_id,
        command_name=body.command_name,
        args=body.args,
        run_at=run_at,
        duration_seconds=body.duration_seconds,
        status="pending",
        created_by=current_user.id,
        repeat_type=body.repeat_type
    )

    try:
        db.add(event)
        db.flush()
        audit.record_change(
            db, current_user.id, "scheduled_event.create", f"scheduled_events:{event.id}"
        )
        db.commit()
        db.refresh(event)

    except Exception:
        db.rollback()
        raise

    return event

@app.get(
    "/barns/{barn_id}/scheduled-events",
    response_model=list[schemas.ScheduledEventResponse]
)
def get_scheduled_events(
    barn_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    check_barn_access(
        barn_id,
        current_user,
        db
    )

    return db.query(
        models.ScheduledEvent
    ).filter(
        models.ScheduledEvent.barn_id == barn_id
    ).order_by(
        models.ScheduledEvent.run_at.asc()
    ).all()


@app.delete("/scheduled-events/{event_id}")
def cancel_scheduled_event(
    event_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles("Admin", "Operator"))
):
    event = db.query(
        models.ScheduledEvent
    ).filter(
        models.ScheduledEvent.id == event_id
    ).first()

    if not event:
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    check_barn_access(
        event.barn_id,
        current_user,
        db
    )

    if event.status != "pending":
        raise HTTPException(
            status_code=409,
            detail="Only pending events can be cancelled"
        )

    event.status = "cancelled"

    audit.record_change(
        db,
        current_user.id,
        "scheduled_event.cancel",
        f"scheduled_events:{event.id}",
        event.status
    )
    db.commit()

    return {
        "message": "Scheduled event cancelled",
        "event_id": event.id
    }


# ---------------------------------------------------------
# Camera AI & Computer Vision Routes
# ---------------------------------------------------------
ALLOWED_CAMERA_SOURCES = [
    s.strip()
    for s in os.getenv("ALLOWED_CAMERA_SOURCES", "0,1").split(",")
    if s.strip()
]


def validate_camera_source(source: str | int | None) -> str | int | None:
    if source is None:
        return None
    source_str = str(source).strip()
    if source_str not in ALLOWED_CAMERA_SOURCES:
        raise HTTPException(
            400,
            f"Nguồn camera '{source}' không nằm trong danh sách cho phép: {ALLOWED_CAMERA_SOURCES}",
        )
    if source_str.isdigit():
        return int(source_str)

    parsed = urllib.parse.urlparse(source_str)
    if parsed.scheme.lower() not in ("rtsp", "rtsps", "http", "https"):
        raise HTTPException(400, "Invalid camera source scheme: only rtsp, rtsps, http, https are allowed")

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(400, "Invalid camera source URL: missing hostname")

    if hostname.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        raise HTTPException(400, "Access to local/internal network camera sources is prohibited")

    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise HTTPException(400, "Access to private or local network camera sources is prohibited")
    except ValueError:
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for entry in addr_info:
                ip_str = entry[4][0]
                ip = ipaddress.ip_address(ip_str)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                    raise HTTPException(400, "Access to private or local network camera sources is prohibited")
        except socket.gaierror:
            raise HTTPException(400, f"Cannot resolve camera hostname: {hostname}")
    return source_str


class CameraConfigBody(BaseModel):
    source: str | int | None = None
    allow_person: bool | None = None
    motionless_sec: float | None = None
    moving_threshold: float | None = None


@app.get("/camera/feed")
async def camera_feed(
    current_user: models.User = Depends(get_current_user_allow_query),
):
    if not camera_streamer:
        raise HTTPException(503, "Camera module not available")
    if not camera_streamer.running:
        raise HTTPException(409, "Camera đang tắt. Vui lòng bấm Bật Camera để bắt đầu.")
    return StreamingResponse(
        camera_streamer.generate_mjpeg(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/camera/status")
async def camera_status(
    current_user: models.User = Depends(get_current_user),
):
    if not camera_streamer:
        return {"is_available": False, "state": "unavailable"}
    return {
        "is_available": True,
        **camera_streamer.get_latest_snapshot(),
        "config": {
            "source": camera_streamer.source,
            "allow_person": camera_streamer.allow_person,
            "motionless_sec": camera_streamer.motionless_sec,
            "moving_threshold": camera_streamer.moving_threshold,
        },
    }


@app.post("/camera/start")
async def camera_start(
    current_user: models.User = Depends(require_roles("Admin", "Operator")),
):
    if not camera_streamer:
        raise HTTPException(503, "Camera module not available")
    # start/stop/update_config mở camera hoặc join luồng (tới 2 s): chạy ngoài event loop
    # để không chặn MQTT gateway và các request khác.
    await asyncio.to_thread(camera_streamer.start)
    return {"ok": True, "running": True}


@app.post("/camera/stop")
async def camera_stop(
    current_user: models.User = Depends(require_roles("Admin", "Operator")),
):
    if not camera_streamer:
        raise HTTPException(503, "Camera module not available")
    await asyncio.to_thread(camera_streamer.stop)
    return {"ok": True, "running": False}


@app.post("/camera/config")
async def camera_config(
    body: CameraConfigBody,
    current_user: models.User = Depends(require_roles("Admin", "Operator")),
):
    # Kiểm tra đầu vào trước: source xấu luôn bị từ chối (400), kể cả khi máy không có camera.
    validated_source = validate_camera_source(body.source) if body.source is not None else None
    if not camera_streamer:
        raise HTTPException(503, "Camera module not available")
    await asyncio.to_thread(
        camera_streamer.update_config,
        allow_person=body.allow_person,
        motionless_sec=body.motionless_sec,
        moving_threshold=body.moving_threshold,
        source=validated_source,
    )
    return {"ok": True, "status": camera_streamer.get_latest_snapshot()}






