"""Persist gateway lifecycle callbacks using a session owned by each worker."""
import asyncio

from .. import models


class LifecycleEventRecorder:
    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._lock = asyncio.Lock()

    async def on_lifecycle_change(self, event):
        async with self._lock:
            await asyncio.to_thread(self._record_sync, event)

    def _record_sync(self, event):
        with self._session_factory() as db:
            if db.get(models.Device, event.device_id) is not None:
                db.add(models.DeviceEvent(
                    device_id=event.device_id,
                    type="lifecycle",
                    detail={"state": event.state, "reason": event.reason},
                    ts=event.at,
                ))
                db.commit()
