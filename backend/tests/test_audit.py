from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from app.services.user import create_user, get_users, update_user


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[table for table in Base.metadata.sorted_tables if table.name != "audit_logs"],
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id CHAR(36),
                action VARCHAR(100) NOT NULL,
                target VARCHAR(255),
                result VARCHAR(100),
                ts DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            )
            """
        )
    with Session(engine) as session:
        session.add(models.User(
            id="actor",
            username="admin",
            password_hash="hash",
            role="Admin",
            status="active",
        ))
        session.commit()
        yield session
    engine.dispose()


def test_user_mutations_are_audited_but_noop_update_is_not(db):
    created = create_user(
        db,
        SimpleNamespace(
            username="viewer",
            password="password123",
            full_name="Viewer",
            role="Viewer",
        ),
        "actor",
    )
    logs = db.query(models.AuditLog).all()
    assert len(logs) == 1
    assert (logs[0].user_id, logs[0].action, logs[0].target, logs[0].result) == (
        "actor", "user.create", created.id, "success"
    )
    get_users(db)
    assert db.query(models.AuditLog).count() == 1

    update_user(
        db,
        created.id,
        SimpleNamespace(role="Viewer", status="active", full_name="Viewer"),
        "actor",
    )
    assert db.query(models.AuditLog).count() == 1

    update_user(
        db,
        created.id,
        SimpleNamespace(role="Operator", status=None, full_name=None),
        "actor",
    )
    assert db.query(models.AuditLog).count() == 2
