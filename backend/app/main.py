"""FastAPI adapter for DeviceGateway."""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from iot_core import (BrokerAuthError, CommandFailed, CommandTimeout, DeviceGateway,
                      DeviceNotFound, DeviceOffline, GatewayConfig, InvalidState,
                      RegistrationNotFound, RegistrationStatus)


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
    env_file = os.environ.get("IOT_ENV_FILE", str(Path(__file__).resolve().parents[2] / "deployment/.env"))
    async with DeviceGateway.from_config(GatewayConfig.from_env(env_file)) as gateway:
        app.state.gateway = gateway
        yield


app = FastAPI(lifespan=lifespan)


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


@app.get("/health")
async def health(request: Request):
    return {"broker_connected": request.app.state.gateway.transport.connected}


@app.get("/devices")
async def devices(request: Request, online: bool | None = None):
    return public(await request.app.state.gateway.list_devices(online))


@app.get("/devices/{device_id}")
async def device(request: Request, device_id: str):
    return public(await request.app.state.gateway.get_device(device_id))


@app.patch("/devices/{device_id}")
async def rename(request: Request, device_id: str, body: RenameBody):
    return public(await request.app.state.gateway.rename(device_id, body.name))


@app.delete("/devices/{device_id}")
async def revoke(request: Request, device_id: str):
    await request.app.state.gateway.revoke(device_id)
    return {"ok": True}


@app.get("/devices/{device_id}/readings")
async def readings(request: Request, device_id: str):
    return public(await request.app.state.gateway.read_all(device_id))


@app.get("/devices/{device_id}/sensors/{sensor}")
async def sensor(request: Request, device_id: str, sensor: str):
    return await request.app.state.gateway.read_sensor(device_id, sensor)


@app.post("/devices/{device_id}/commands")
async def command(request: Request, device_id: str, body: CommandBody):
    return await request.app.state.gateway.send_command(device_id, body.name, body.args, body.timeout_s)


@app.post("/devices/{device_id}/ping")
async def ping(request: Request, device_id: str):
    return await request.app.state.gateway.ping(device_id)


@app.post("/devices/{device_id}/reboot")
async def reboot(request: Request, device_id: str):
    await request.app.state.gateway.reboot(device_id)
    return {"ok": True}


@app.put("/devices/{device_id}/interval")
async def interval(request: Request, device_id: str, body: IntervalBody):
    return {"interval_s": await request.app.state.gateway.set_interval(device_id, body.seconds)}


@app.get("/devices/{device_id}/telemetry")
async def telemetry(request: Request, device_id: str, limit: int = Query(100, ge=1), since: datetime | None = None):
    return public(await request.app.state.gateway.telemetry_history(device_id, limit, since))


@app.get("/devices/{device_id}/telemetry/latest")
async def latest(request: Request, device_id: str):
    return public(await request.app.state.gateway.latest_telemetry(device_id))


@app.get("/registrations")
async def registrations(request: Request, status: Literal["pending", "approved", "rejected", "revoked", "all"] = "pending"):
    state = None if status == "all" else RegistrationStatus(status)
    return public(await request.app.state.gateway.list_registrations(state))


@app.post("/registrations/{hw_id}/approve")
async def approve(request: Request, hw_id: str, body: ApproveBody):
    return public(await request.app.state.gateway.approve(hw_id, device_id=body.device_id, name=body.name))


@app.post("/registrations/{hw_id}/reject")
async def reject(request: Request, hw_id: str, body: RejectBody):
    return public(await request.app.state.gateway.reject(hw_id, body.reason))


@app.get("/events")
async def events(request: Request):
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
        try:
            while not await request.is_disconnected():
                try:
                    kind, data = await asyncio.wait_for(queue.get(), 15)
                    yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            for unsubscribe in unsubscribes:
                unsubscribe()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
