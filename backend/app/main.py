"""FastAPI adapter for DeviceGateway."""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
from contextlib import asynccontextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path
from typing import Any, Literal, Optional


from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

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
from .services import alert, audit, barn, user, auth, command, scheduler
from iot_core import (BrokerAuthError, CommandFailed, CommandTimeout, DeviceGateway,
                      DeviceNotFound, DeviceOffline, GatewayConfig, InvalidState,
                      RegistrationNotFound, RegistrationStatus)

from . import models

from . import schemas


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
app.state.firmware_jobs = {}
app.state.firmware_tasks = set()
app.state.ota_listeners = set()


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
    name: str


class CommandBody(BaseModel):
    name: str
    args: dict[str, Any] | None = None
    timeout_s: float | None = Field(default=None, gt=0)


class IntervalBody(BaseModel):
    seconds: int = Field(ge=1, le=3600, strict=True)


class ApproveBody(BaseModel):
    device_id: str | None = None
    name: str = ""


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

security = HTTPBearer(auto_error=True)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    return auth.get_current_user(
        db,
        credentials.credentials
    )


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
    current_user: models.User = Depends(get_current_user)
):
    return public(await request.app.state.gateway.list_devices(online))


@app.get("/devices/{device_id}")
async def device(
    request: Request,
    device_id: str,
    current_user: models.User = Depends(get_current_user)
):
    return public(await request.app.state.gateway.get_device(device_id))


@app.patch("/devices/{device_id}")
async def rename(
    request: Request,
    device_id: str,
    body: RenameBody,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    device = check_device_write_access(device_id, db, current_user)
    result = public(await request.app.state.gateway.rename(device_id, body.name))
    if device.name != body.name:
        audit.record_change(db, current_user.id, "device.rename", f"devices:{device_id}")
        db.commit()
    return result


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


@app.get("/devices/{device_id}/readings")
async def readings(
    request: Request,
    device_id: str,
    current_user: models.User = Depends(get_current_user)
):
    return public(await request.app.state.gateway.read_all(device_id))


@app.get("/devices/{device_id}/sensors/{sensor}")
async def sensor(
    request: Request,
    device_id: str,
    sensor: str,
    current_user: models.User = Depends(get_current_user)
):
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
    return await request.app.state.gateway.send_command(device_id, body.name, body.args, body.timeout_s)


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
    current_user: models.User = Depends(get_current_user)
):
    return public(await request.app.state.gateway.telemetry_history(device_id, limit, since))


@app.get("/devices/{device_id}/telemetry/latest")
async def latest(
    request: Request,
    device_id: str,
    current_user: models.User = Depends(get_current_user)
):
    return public(await request.app.state.gateway.latest_telemetry(device_id))


@app.get("/registrations")
async def registrations(
    request: Request,
    status: Literal["pending", "approved", "rejected", "revoked", "all"] = "pending",
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
    result = public(await request.app.state.gateway.approve(
        hw_id, device_id=body.device_id, name=body.name
    ))
    audit.record_change(
        db, current_user.id, "registration.approve", f"registrations:{hw_id}"
    )
    db.commit()
    return result


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


@app.get("/events")
async def events(
    request: Request,
    current_user: models.User = Depends(get_current_user)
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





