
from pydantic import BaseModel, Field, EmailStr, ConfigDict


from datetime import datetime
from typing import Optional, Any, Literal

from pydantic import BaseModel, Field, ConfigDict


# =========================================
# COMMON
# =========================================

class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# =========================================
# 1. AUTHENTICATION
# =========================================

class LoginSchema(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=72)


class RefreshTokenSchema(BaseModel):
    refresh_token: str


class UserRegisterSchema(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=72)
    full_name: Optional[str] = None
    role: Literal["Admin", "Operator", "Viewer"] = "Viewer"


class ChangePasswordSchema(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=72)


class TokenResponse(BaseModel):
    message: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 1800
    user: dict[str, Any]


# =========================================
# 2. USERS
# =========================================

class UserResponse(ORMBase):
    id: str
    username: str
    full_name: Optional[str] = None
    role: str
    status: str
    created_at: Optional[datetime] = None


class UserUpdateSchema(BaseModel):
    role: Optional[Literal["Admin", "Operator", "Viewer"]] = None
    status: Optional[Literal["active", "locked"]] = None
    full_name: Optional[str] = None


# =========================================
# 3. BARNS
# =========================================

class BarnCreateSchema(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    zone: Optional[str] = None
    animal_type: Optional[str] = None


class BarnUpdateSchema(BaseModel):
    name: Optional[str] = None
    zone: Optional[str] = None
    animal_type: Optional[str] = None


class BarnResponse(ORMBase):
    id: str
    name: str
    zone: Optional[str] = None
    animal_type: Optional[str] = None


# =========================================
# 4. BARN ASSIGNMENTS
# =========================================

class BarnAssignmentItem(BaseModel):
    user_id: str
    access_level: Literal["Operator", "Viewer"]


class BarnAssignmentSchema(BaseModel):
    assignments: list[BarnAssignmentItem]


class BarnAssignmentDeleteSchema(BaseModel):
    user_id: str


class BarnAssignmentResponse(ORMBase):
    user_id: str
    barn_id: str
    access_level: str


# =========================================
# 5. DEVICES
# =========================================

class DeviceCreateSchema(BaseModel):
    hw_id: str = Field(min_length=1, max_length=100)
    barn_id: Optional[str] = None

    name: str = ""
    model: str = ""
    fw: str = ""

    sensors: Optional[dict[str, Any]] = None
    commands: Optional[dict[str, Any]] = None

    interval_s: Optional[int] = Field(default=None, gt=0)
    hw_version: Optional[str] = None


class DeviceResponse(ORMBase):
    device_id: str
    hw_id: str
    barn_id: Optional[str] = None

    name: str
    model: str
    fw: str

    sensors: Optional[Any] = None
    commands: Optional[Any] = None

    interval_s: Optional[int] = None
    status: str

    last_seen: Optional[datetime] = None
    registered_at: Optional[datetime] = None
    hw_version: Optional[str] = None


class DeviceCredentialResponse(BaseModel):
    device_id: str
    hw_id: str
    mqtt_username: str
    mqtt_password: str


class DeviceLifecycleSchema(BaseModel):
    reason: Optional[str] = None


class DeviceRotateCredentialResponse(BaseModel):
    device_id: str
    mqtt_username: str
    mqtt_password: str


# =========================================
# 6. REGISTRATIONS
# =========================================

class RegistrationResponse(ORMBase):
    hw_id: str
    status: str
    requested_at: datetime
    updated_at: datetime

    model: Optional[str] = None
    fw: Optional[str] = None

    sensors: Optional[Any] = None
    commands: Optional[Any] = None

    device_id: Optional[str] = None
    reason: Optional[str] = None


# =========================================
# 7. TELEMETRY
# =========================================

class TelemetryResponse(ORMBase):
    id: int
    device_id: str
    received_at: datetime
    device_ts: Optional[float] = None
    readings: dict[str, Any]


class TelemetryQuerySchema(BaseModel):
    from_time: Optional[datetime] = None
    to_time: Optional[datetime] = None
    agg: Optional[Literal["raw", "hour", "day"]] = "raw"


# =========================================
# 8. COMMANDS
# =========================================

class CommandCreateSchema(BaseModel):
    action: str = Field(min_length=1, max_length=100)
    params: Optional[dict[str, Any]] = None


class CommandResponse(ORMBase):
    command_id: str
    device_id: str
    user_id: str

    action: str
    params: Optional[dict[str, Any]] = None

    status: str
    issued_at: Optional[datetime] = None
    acked_at: Optional[datetime] = None


# =========================================
# 9. DEVICE CONFIGS
# =========================================

class DeviceConfigSchema(BaseModel):
    version: int = Field(gt=0)
    body: dict[str, Any]


class DeviceConfigResponse(ORMBase):
    device_id: str
    version: int
    body: dict[str, Any]
    applied_at: Optional[datetime] = None


# =========================================
# 10. DEVICE EVENTS
# =========================================

class DeviceEventResponse(ORMBase):
    id: int
    device_id: str
    type: str
    detail: Optional[dict[str, Any]] = None
    ts: datetime


# =========================================
# 11. ALERT RULES
# =========================================

class AlertRuleCreateSchema(BaseModel):
    metric: str
    op: Literal[">", "<", ">=", "<=", "==", "!="]
    threshold: float
    hold_samples: int = Field(default=1, ge=1)
    severity: Literal["info", "warning", "critical"]


class AlertRuleResponse(ORMBase):
    id: str
    barn_id: str
    metric: str
    op: str
    threshold: float
    hold_samples: int
    severity: str


# =========================================
# 12. ALERTS
# =========================================

class AlertResponse(ORMBase):
    id: str
    rule_id: Optional[str] = None
    device_id: Optional[str] = None

    severity: str
    status: str

    handled_by: Optional[str] = None
    note: Optional[str] = None

    raised_at: datetime
    closed_at: Optional[datetime] = None


class AlertActionSchema(BaseModel):
    note: Optional[str] = None


# =========================================
# 13. AUDIT LOGS
# =========================================

class AuditLogResponse(ORMBase):
    id: int
    user_id: Optional[str] = None

    action: str
    target: Optional[str] = None

    result: Optional[str] = None
    ts: Optional[datetime] = None


# =========================================
# 14. ERROR RESPONSE
# =========================================

class ErrorResponse(BaseModel):
    detail: str

# =========================================
# 15. Scheluled Events
# =========================================


class ScheduledEventCreateSchema(BaseModel):
    device_id: str = Field(min_length=1, max_length=100)
    command_name: str = Field(min_length=1, max_length=100)

    args: dict[str, Any] | None = None

    run_at: datetime

    # Maximum time to wait for MQTT command (seconds)
    duration_seconds: int = Field(
        default=10,
        ge=1,
        le=86400
    )

    repeat_type: Literal[
        "once",
        "daily",
        "weekly",
        "monthly"
    ] = "once"


class ScheduledEventResponse(BaseModel):
    id: str
    barn_id: str
    device_id: str
    command_name: str

    args: dict[str, Any] | None = None

    run_at: datetime
    duration_seconds: int | None = None

    status: str
    error: str | None = None

    executed_at: datetime | None = None
    created_at: datetime | None = None

    repeat_type: str

    model_config = ConfigDict(from_attributes=True)
