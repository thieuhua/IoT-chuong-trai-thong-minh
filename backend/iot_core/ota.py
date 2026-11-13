"""Over-the-air firmware update driven through ota_* commands (docs/protocol.md section 7).

begin (device reports which files differ) -> chunks for those files -> commit (device reboots, its
loader installs the new /app) -> wait until the new version is online and confirmed, or detect the
loader's rollback. Chunks are idempotent on the device, so lost answers are simply retried.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import inspect
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from .errors import CommandFailed, CommandTimeout, DeviceOffline

if TYPE_CHECKING:
    from .gateway import DeviceGateway

CHUNK_SIZE = 2048            # raw bytes; base64 + envelope stays under protocol.MAX_PAYLOAD
RETRIES = 3
Progress = Callable[[dict[str, Any]], "Awaitable[None] | None"]


def manifest(files: dict[str, bytes]) -> list[dict[str, Any]]:
    if not files:
        raise ValueError("no files to send")
    if "app.py" not in files:
        raise ValueError("an update must contain app.py")
    return [{"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for path, data in sorted(files.items())]


async def _report(on_progress: Progress | None, **event: Any) -> None:
    if on_progress is not None:
        result = on_progress(event)
        if inspect.isawaitable(result):
            await result


async def _command(gw: DeviceGateway, device_id: str, name: str, args: dict[str, Any] | None = None,
                   timeout_s: float = 15.0) -> dict[str, Any]:
    for attempt in range(1, RETRIES + 1):
        try:
            return await gw.send_command(device_id, name, args, timeout_s=timeout_s)
        except CommandTimeout:
            if attempt == RETRIES:
                raise


async def update(gw: DeviceGateway, device_id: str, files: dict[str, bytes], version: str, *,
                 on_progress: Progress | None = None, wait_confirm: bool = True,
                 confirm_timeout_s: float = 720.0) -> dict[str, Any]:
    entries = manifest(files)
    await _report(on_progress, stage="begin", files=len(entries))
    begin = await _command(gw, device_id, "ota_begin", {"version": version, "files": entries}, 60)
    need = list(begin.get("need", []))
    done = dict(begin.get("written") or {})
    total = sum(len(files[p]) for p in need)
    sent = sum(min(done.get(p, 0), len(files[p])) for p in need)
    await _report(on_progress, stage="upload", sent=sent, total=total, need=need)
    try:
        for path in need:
            data = files[path]
            offset = done.get(path, 0)
            while offset < len(data):
                piece = data[offset:offset + CHUNK_SIZE]
                result = await _command(gw, device_id, "ota_chunk", {
                    "path": path, "offset": offset, "data": base64.b64encode(piece).decode()})
                written = result.get("written")
                if type(written) is not int or not offset < written <= len(data):
                    # Must advance and stay inside the file, or the loop would spin or skip data.
                    raise CommandFailed("ota_error", f"{path}: device reported written={written!r} "
                                                     f"after offset {offset} of {len(data)}")
                sent += written - offset
                offset = written
                await _report(on_progress, stage="upload", sent=sent, total=total, path=path)
        await _report(on_progress, stage="commit")
        await _command(gw, device_id, "ota_commit", timeout_s=60)
    except BaseException:
        try:
            await gw.send_command(device_id, "ota_abort", timeout_s=5)
        except Exception:
            pass
        raise
    result = {"device_id": device_id, "version": version, "files": len(entries),
              "sent_files": len(need), "sent_bytes": total}
    if not wait_confirm:
        return {**result, "state": "committed"}
    return {**result, **await _wait_confirmed(gw, device_id, version, on_progress, confirm_timeout_s)}


async def _wait_confirmed(gw: DeviceGateway, device_id: str, version: str,
                          on_progress: Progress | None, timeout_s: float) -> dict[str, Any]:
    """The device reboots, installs, comes back in trial mode and confirms after ~30 s online."""
    await _report(on_progress, stage="reboot")
    deadline = time.monotonic() + timeout_s
    await asyncio.sleep(3)  # let it go offline before polling
    while time.monotonic() < deadline:
        try:
            status = await gw.send_command(device_id, "ota_status", timeout_s=10)
        except (DeviceOffline, CommandTimeout):
            await asyncio.sleep(3)
            continue
        if status.get("rolled_back_from") == version and status.get("version") != version:
            raise CommandFailed("ota_error", f"device rolled back to {status.get('version')}")
        if status.get("version") == version:
            if status.get("state") == "ok":
                await _report(on_progress, stage="done")
                return {"state": "confirmed"}
            await _report(on_progress, stage="trial", boots=status.get("boots"))
        await asyncio.sleep(5)
    raise CommandTimeout(f"{device_id}: version {version} not confirmed within {timeout_s:.0f} s")
