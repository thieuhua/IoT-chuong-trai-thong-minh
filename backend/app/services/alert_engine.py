"""Gateway callbacks. Each worker operation owns its SQLAlchemy session."""
import asyncio
import math
import operator
from uuid import uuid4

from .. import models


class AlertEngine:
    OPERATORS = {">": operator.gt, "<": operator.lt, ">=": operator.ge,
                 "<=": operator.le, "==": operator.eq, "!=": operator.ne}

    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._counts = {}
        # Serialize the open lookup + insert across device MQTT workers.
        self._lock = asyncio.Lock()

    async def on_telemetry(self, record):
        async with self._lock:
            await asyncio.to_thread(self._telemetry_sync, record)

    async def on_status_change(self, event):
        async with self._lock:
            await asyncio.to_thread(self._status_sync, event)

    @staticmethod
    def _metric_values(readings, metric):
        path = metric.removeprefix("readings.").split(".")
        if len(path) > 1:
            if path[0] in readings.errors:
                return []
            value = readings.values
            for part in path:
                value = value.get(part) if isinstance(value, dict) else None
            values = [value]
        else:
            values = [value.get(metric) for sensor, value in readings.values.items()
                      if sensor not in readings.errors and isinstance(value, dict)]
        return [value for value in values
                if isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value)]

    @staticmethod
    def _open_alert(db, device_id, rule_id, severity, at):
        existing = db.query(models.Alert).filter(
            models.Alert.device_id == device_id, models.Alert.rule_id == rule_id,
            models.Alert.status == "open",
        ).first()
        if existing is None:
            db.add(models.Alert(id=str(uuid4()), device_id=device_id, rule_id=rule_id,
                                severity=severity, status="open", raised_at=at))
            db.flush()

    def _telemetry_sync(self, record):
        with self._session_factory() as db:
            device = db.get(models.Device, record.device_id)
            rules = (db.query(models.AlertRule).filter(
                models.AlertRule.barn_id == device.barn_id).all()
                if device is not None and device.barn_id else [])
            active = {(record.device_id, rule.id) for rule in rules}
            self._counts = {key: value for key, value in self._counts.items()
                            if key[0] != record.device_id or key in active}
            for rule in rules:
                key = (record.device_id, rule.id)
                signature = (rule.barn_id, rule.metric, rule.op, rule.threshold,
                             rule.hold_samples, rule.severity)
                old_signature, count = self._counts.get(key, (None, 0))
                compare = self.OPERATORS.get(rule.op)
                values = self._metric_values(record.readings, rule.metric)
                breached = compare is not None and any(compare(v, rule.threshold) for v in values)
                count = (count + 1 if old_signature == signature else 1) if breached else 0
                hold = max(1, rule.hold_samples or 1)
                self._counts[key] = (signature, min(count, hold))
                if count >= hold:
                    self._open_alert(db, record.device_id, rule.id, rule.severity,
                                     record.received_at)
            db.commit()

    def _status_sync(self, event):
        if event.online:
            return
        self._counts = {key: value for key, value in self._counts.items()
                        if key[0] != event.device_id}
        with self._session_factory() as db:
            if db.get(models.Device, event.device_id) is not None:
                self._open_alert(db, event.device_id, None, "critical", event.at)
                db.commit()
