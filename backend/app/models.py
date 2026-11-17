from datetime import datetime, timezone
import uuid

from sqlalchemy import (
    Column,
    String,
    Integer,
    BigInteger,
    Float,
    DateTime,
    ForeignKey,
    Text,
    Boolean,
    JSON,
    Index,
    UniqueConstraint,
    func
)

from sqlalchemy.orm import relationship

from .database import Base



# =========================================
# 1. USERS
# =========================================

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)

    full_name = Column(String(255))
    role = Column(String(30), nullable=False, default="Viewer")
    status = Column(String(30), nullable=False, default="active")
    created_at = Column(DateTime, server_default=func.current_timestamp())

    sessions = relationship(
        "AuthSession",
        back_populates="user",
        cascade="all, delete-orphan"
    )


# =========================================
# 2. AUTH SESSIONS
# Refresh token management
# =========================================

class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    jti = Column(String(255), unique=True, nullable=False, index=True)

    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Integer, nullable=False, default=0)

    user = relationship(
        "User",
        back_populates="sessions"
    )


# =========================================
# 3. BARNS
# =========================================

class Barn(Base):
    __tablename__ = "barns"

    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)
    zone = Column(String(100))
    animal_type = Column(String(100))

    assignments = relationship(
        "BarnAssignment",
        back_populates="barn",
        cascade="all, delete-orphan"
    )

    devices = relationship(
        "Device",
        back_populates="barn"
    )


# =========================================
# 4. BARN ASSIGNMENTS
# =========================================

class BarnAssignment(Base):
    __tablename__ = "barn_assignments"

    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True
    )

    barn_id = Column(
        String(36),
        ForeignKey("barns.id", ondelete="CASCADE"),
        primary_key=True
    )

    access_level = Column(String(30), nullable=False)

    user = relationship("User")
    barn = relationship("Barn", back_populates="assignments")


# =========================================
# 5. DEVICES
# =========================================

class Device(Base):
    __tablename__ = "devices"

    device_id = Column(String(100), primary_key=True)
    hw_id = Column(String(100), unique=True, nullable=False)

    barn_id = Column(
        String(36),
        ForeignKey("barns.id", ondelete="SET NULL"),
        unique=True
    )

    name = Column(String(255), default="")
    model = Column(String(100), default="")
    fw = Column(String(100), default="")

    sensors = Column(JSON)
    commands = Column(JSON)

    interval_s = Column(Integer)

    status = Column(String(30), nullable=False, default="offline")
    last_seen = Column(DateTime)
    registered_at = Column(DateTime)

    hw_version = Column(String(100))
    mqtt_secret_hash = Column(String(255))

    barn = relationship("Barn", back_populates="devices")

    telemetry = relationship(
        "Telemetry",
        back_populates="device",
        cascade="all, delete-orphan"
    )


# =========================================
# 6. REGISTRATIONS
# =========================================

class Registration(Base):
    __tablename__ = "registrations"

    hw_id = Column(String(100), primary_key=True)

    status = Column(String(20), nullable=False)

    requested_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    model = Column(String(100), default="")
    fw = Column(String(100), default="")

    sensors = Column(JSON)
    commands = Column(JSON)

    device_id = Column(
        String(100),
        ForeignKey("devices.device_id", ondelete="SET NULL")
    )

    reason = Column(Text)

    password = Column(String(255))
    password_hash = Column(String(64))


# =========================================
# 7. TELEMETRY
# =========================================

class Telemetry(Base):
    __tablename__ = "telemetry"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    device_id = Column(
        String(100),
        ForeignKey("devices.device_id", ondelete="CASCADE"),
        nullable=False
    )

    received_at = Column(DateTime, nullable=False)
    device_ts = Column(Float)

    readings = Column(JSON, nullable=False)

    device = relationship("Device", back_populates="telemetry")

    __table_args__ = (
        Index(
            "idx_telemetry_device_time",
            "device_id",
            "received_at",
            "id"
        ),
    )


# =========================================
# 8. COMMANDS
# =========================================

class Command(Base):
    __tablename__ = "commands"

    command_id = Column(String(100), primary_key=True)

    device_id = Column(
        String(100),
        ForeignKey("devices.device_id", ondelete="CASCADE"),
        nullable=False
    )

    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False
    )

    action = Column(String(100), nullable=False)
    params = Column(JSON)

    status = Column(String(30), nullable=False, default="pending")

    issued_at = Column(
        DateTime,
        server_default=func.current_timestamp()
    )

    acked_at = Column(DateTime)


# =========================================
# 9. DEVICE CONFIGS
# =========================================

class DeviceConfig(Base):
    __tablename__ = "device_configs"

    device_id = Column(
        String(100),
        ForeignKey("devices.device_id", ondelete="CASCADE"),
        primary_key=True
    )

    version = Column(Integer, primary_key=True)

    body = Column(JSON, nullable=False)
    applied_at = Column(DateTime)


# =========================================
# 10. DEVICE EVENTS
# =========================================

class DeviceEvent(Base):
    __tablename__ = "device_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    device_id = Column(
        String(100),
        ForeignKey("devices.device_id", ondelete="CASCADE"),
        nullable=False
    )

    type = Column(String(50), nullable=False)
    detail = Column(JSON)

    ts = Column(DateTime, nullable=False)

    __table_args__ = (
        Index(
            "idx_device_events_time",
            "device_id",
            "ts"
        ),
    )


# =========================================
# 11. ALERT RULES
# =========================================

class AlertRule(Base):
    __tablename__ = "alert_rules"

    id = Column(String(36), primary_key=True)

    barn_id = Column(
        String(36),
        ForeignKey("barns.id", ondelete="CASCADE"),
        nullable=False
    )

    metric = Column(String(100), nullable=False)
    op = Column(String(10), nullable=False)

    threshold = Column(Float, nullable=False)
    hold_samples = Column(Integer, default=1)

    severity = Column(String(30), nullable=False)


# =========================================
# 12. ALERTS
# =========================================

class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String(36), primary_key=True)

    rule_id = Column(
        String(36),
        ForeignKey("alert_rules.id", ondelete="SET NULL")
    )

    device_id = Column(
        String(100),
        ForeignKey("devices.device_id", ondelete="SET NULL")
    )

    severity = Column(String(30), nullable=False)
    status = Column(String(30), nullable=False, default="open")

    handled_by = Column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL")
    )

    note = Column(Text)

    raised_at = Column(DateTime, nullable=False)
    closed_at = Column(DateTime)


# =========================================
# 13. AUDIT LOGS
# =========================================

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL")
    )

    action = Column(String(100), nullable=False)
    target = Column(String(255))

    result = Column(String(100))

    ts = Column(
        DateTime,
        server_default=func.current_timestamp()
    )

# =========================================
# 14. Scheduled Events
# =========================================

class ScheduledEvent(Base):
    __tablename__ = "scheduled_events"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    barn_id = Column(
        String(36),
        ForeignKey("barns.id"),
        nullable=False
    )

    device_id = Column(
        String(100),
        nullable=False
    )

    command_name = Column(
        String(100),
        nullable=False
    )

    args = Column(JSON, nullable=True)

    # Scheduled execution time
    run_at = Column(
        DateTime,
        nullable=False
    )

    status = Column(
        String(20),
        nullable=False,
        default="pending"
    )

    error = Column(
        Text,
        nullable=True
    )

    created_by = Column(
        String(36),
        ForeignKey("users.id"),
        nullable=False
    )

    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc)
    )

    repeat_type = Column(
        String(20),
        nullable=False,
        default="once"
    )
    duration_seconds = Column(
        Integer,
        nullable=True,
        default=10
    )

    executed_at = Column(
        DateTime,
        nullable=True
    )