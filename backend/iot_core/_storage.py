"""SQLite JSON serialization shared by the two stores."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum

from .models import SensorSpec


def utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def dumps(value: object) -> str:
    def encode(item: object):
        if isinstance(item, datetime):
            return utc(item)
        if isinstance(item, Enum):
            return item.value
        raise TypeError(type(item).__name__)
    return json.dumps(asdict(value), default=encode, ensure_ascii=False)


def load_row(raw: str, cls):
    data = json.loads(raw)
    for key in ('last_seen', 'registered_at', 'requested_at', 'updated_at'):
        if data.get(key):
            data[key] = datetime.fromisoformat(data[key])
    data['sensors'] = [SensorSpec.from_dict(s) for s in data['sensors']]
    if 'status' in data:
        from .models import RegistrationStatus
        data['status'] = RegistrationStatus(data['status'])
    return cls(**data)
