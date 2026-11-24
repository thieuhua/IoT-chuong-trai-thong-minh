"""Account editing, Admin safeguards, assignment synchronization and reset audit."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.database import Base
from app.main import app, check_barn_access, get_current_user, get_db
from app.services import auth, user
from test_app import _http


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "SECRET_KEY", "account-admin-unit-test-secret-" + "x" * 32)
    engine = create_engine(f"sqlite:///{tmp_path / 'accounts.db'}",
                           connect_args={"check_same_thread": False})
    tables = [models.User, models.AuthSession, models.Barn, models.BarnAssignment]
    Base.metadata.create_all(engine, tables=[model.__table__ for model in tables])
    # MySQL BIGINT audit IDs need INTEGER for SQLite autoincrement.
    with engine.begin() as connection:
        connection.exec_driver_sql("""CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id VARCHAR(36),
            action VARCHAR(100), target VARCHAR(255), result VARCHAR(100), ts DATETIME)""")
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        db.add_all([
            models.User(id="admin", username="admin", role="Admin", status="active", password_hash="unused"),
            models.User(id="other", username="other", role="Admin", status="active", password_hash="unused"),
            models.User(id="viewer", username="viewer", role="Viewer", status="active", password_hash="unused"),
            models.User(id="operator", username="operator", role="Operator", status="active", password_hash="unused"),
            models.Barn(id="one", name="One"), models.Barn(id="two", name="Two"),
        ])
        db.flush()
        for role in ["viewer", "operator"]:
            for barn_id in ["one", "two"]:
                db.add(models.BarnAssignment(user_id=role, barn_id=barn_id, access_level=role.title()))
        db.add_all([
            models.AuthSession(jti="viewer-1", user_id="viewer", expires_at=datetime.utcnow() + timedelta(days=1)),
            models.AuthSession(jti="viewer-2", user_id="viewer", expires_at=datetime.utcnow() + timedelta(days=2)),
            models.AuthSession(jti="admin-1", user_id="admin", expires_at=datetime.utcnow() + timedelta(days=1)),
        ])
        db.commit()
    yield factory
    engine.dispose()


@pytest.fixture
def access(database):
    saved = app.dependency_overrides.copy()
    actor = SimpleNamespace(id="admin", role="Admin", status="active")

    def session():
        with database() as db:
            yield db

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = lambda: actor
    yield actor
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


async def test_admin_reset_hashes_password_revokes_only_target_sessions_and_audits(database, access):
    refresh_token, jti = auth.create_token("viewer", "refresh", timedelta(days=1))
    with database() as db:
        db.query(models.AuthSession).filter_by(jti="viewer-1").one().jti = jti
        db.commit()
    status, result = await _http("PUT", "/users/viewer/password", {"new_password": "NewPassword123!"}, b"")
    assert status == 200
    assert set(result) == {"message"}
    with database() as db:
        target = db.get(models.User, "viewer")
        assert auth.verify_password("NewPassword123!", target.password_hash)
        assert not auth.verify_password("OldPassword123!", target.password_hash)
        assert target.password_hash != "NewPassword123!"
        sessions = {row.jti: row.revoked for row in db.query(models.AuthSession).all()}
        assert sessions == {jti: 1, "viewer-2": 1, "admin-1": 0}
        log = db.query(models.AuditLog).one()
        assert (log.user_id, log.action, log.target, log.result) == (
            "admin", "user.password_reset", "users:viewer", "success")
        assert "NewPassword" not in str(vars(log))
    # Existing refresh tokens are rejected; a fresh login accepts the new password.
    status, _ = await _http("POST", "/auth/refresh", {"refresh_token": refresh_token}, b"")
    assert status == 401
    status, _ = await _http("POST", "/auth/login", {"username": "viewer", "password": "NewPassword123!"}, b"")
    assert status == 200


@pytest.mark.parametrize("role", ["Viewer", "Operator"])
async def test_non_admin_cannot_edit_or_reset_password(database, access, role):
    access.role = role
    access.id = role.lower()
    for method, path, body in [
        ("PUT", "/users/other/password", {"new_password": "NewPassword123!"}),
        ("PATCH", "/users/other", {"role": "Viewer"}),
    ]:
        status, _ = await _http(method, path, body, b"")
        assert status == 403
    with database() as db:
        assert db.query(models.AuditLog).count() == 0


@pytest.mark.parametrize("target,body,expected", [
    ("missing", {"new_password": "NewPassword123!"}, 404),
    ("admin", {"new_password": "NewPassword123!"}, 409),
    ("viewer", {}, 422),
    ("viewer", {"new_password": "short"}, 422),
    ("viewer", {"new_password": "x" * 73}, 422),
    ("viewer", {"new_password": "ế" * 25}, 422),
])
async def test_password_reset_rejections_do_not_mutate(database, access, target, body, expected):
    status, _ = await _http("PUT", f"/users/{target}/password", body, b"")
    assert status == expected
    with database() as db:
        assert db.query(models.AuditLog).count() == 0
        assert all(row.password_hash == "unused" for row in db.query(models.User).all())
        assert not any(row.revoked for row in db.query(models.AuthSession).all())


@pytest.mark.parametrize("body", [{"role": "Viewer"}, {"role": "Operator"}, {"status": "locked"},
                                  {"role": "Viewer", "status": "locked", "full_name": "Blocked"}])
async def test_admin_cannot_demote_or_lock_self_even_with_another_admin(database, access, body):
    status, _ = await _http("PATCH", "/users/admin", body, b"")
    assert status == 400
    with database() as db:
        target = db.get(models.User, "admin")
        assert (target.role, target.status, target.full_name) == ("Admin", "active", None)
        assert db.query(models.AuditLog).count() == 0


@pytest.mark.parametrize("body", [{"role": "Viewer"}, {"role": "Operator"}, {"status": "locked"},
                                  {"role": "Viewer", "status": "locked"}])
def test_last_active_admin_guard_in_service_including_locked_other_admin(database, body):
    with database() as db:
        db.get(models.User, "other").status = "locked"
        db.commit()
        # Test the last-Admin rule independently of the route's self-edit guard.
        with pytest.raises(HTTPException) as error:
            user.update_user(db, "admin", schemas.UserUpdateSchema(**body))
        assert error.value.status_code == 409
        assert "ít nhất" in error.value.detail
        db.rollback()
        assert (db.get(models.User, "admin").role, db.get(models.User, "admin").status) == ("Admin", "active")
        assert db.query(models.AuditLog).count() == 0


@pytest.mark.parametrize("body", [{"role": "Viewer"}, {"status": "locked"}])
async def test_other_admin_can_be_demoted_or_locked_while_active_admin_remains(database, access, body):
    status, result = await _http("PATCH", "/users/other", body, b"")
    assert status == 200
    for key, value in body.items():
        assert result[key] == value
    with database() as db:
        assert db.get(models.User, "admin").status == "active"
        assert db.query(models.AuditLog).one().action == "user.update"


@pytest.mark.parametrize("target,role", [("viewer", "Operator"), ("operator", "Viewer")])
async def test_role_change_preserves_barns_and_updates_access_and_audit(database, access, target, role):
    status, result = await _http("PATCH", f"/users/{target}", {"role": role, "full_name": "Tên mới"}, b"")
    assert status == 200
    assert (result["role"], result["full_name"]) == (role, "Tên mới")
    assert "password_hash" not in result
    with database() as db:
        grants = db.query(models.BarnAssignment).filter_by(user_id=target).all()
        assert {grant.barn_id for grant in grants} == {"one", "two"}
        assert {grant.access_level for grant in grants} == {role}
        for grant in grants:
            assert check_barn_access(grant.barn_id, db.get(models.User, target), db)
        logs = db.query(models.AuditLog).all()
        assert sorted(log.action for log in logs) == ["barn.assignment.update", "barn.assignment.update", "user.update"]
        assert all(log.user_id == "admin" and log.result == "success" for log in logs)
    # No-op must not duplicate audit entries.
    status, _ = await _http("PATCH", f"/users/{target}", {"role": role, "full_name": "Tên mới"}, b"")
    assert status == 200
    with database() as db:
        assert db.query(models.AuditLog).count() == 3


async def test_promoting_admin_removes_explicit_grants_and_demotion_requires_new_grants(database, access):
    status, _ = await _http("PATCH", "/users/viewer", {"role": "Admin"}, b"")
    assert status == 200
    with database() as db:
        assert db.query(models.BarnAssignment).filter_by(user_id="viewer").count() == 0
        assert db.query(models.AuditLog).filter_by(action="barn.assignment.remove").count() == 2
    status, _ = await _http("PATCH", "/users/viewer", {"role": "Operator"}, b"")
    assert status == 200
    status, _ = await _http("PUT", "/barns/one/assignments", {
        "assignments": [{"user_id": "viewer", "access_level": "Operator"}]}, b"")
    assert status == 200
    status, grants = await _http("GET", "/barns/one/assignments", None, b"")
    assert status == 200
    assert any(grant["user_id"] == "viewer" and grant["access_level"] == "Operator" for grant in grants)
    status, _ = await _http("DELETE", "/barns/one/assignments", {"user_id": "viewer"}, b"")
    assert status == 200


async def test_self_name_edit_and_missing_account(database, access):
    status, result = await _http("PATCH", "/users/admin", {"full_name": "Quản trị"}, b"")
    assert status == 200 and result["full_name"] == "Quản trị"
    status, _ = await _http("PATCH", "/users/missing", {"role": "Viewer"}, b"")
    assert status == 404


def test_password_reset_rolls_back_hash_and_sessions_when_audit_fails(database, monkeypatch):
    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(user, "record_change", fail_audit)
    with database() as db:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            user.reset_password(db, "viewer", schemas.AdminPasswordResetSchema(new_password="NewPassword123!"), "admin")
        assert db.get(models.User, "viewer").password_hash == "unused"
        assert not any(row.revoked for row in db.query(models.AuthSession).all())


def test_role_update_rolls_back_assignments_when_audit_fails(database, monkeypatch):
    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(user, "record_change", fail_audit)
    with database() as db:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            user.update_user(db, "viewer", schemas.UserUpdateSchema(role="Operator"), "admin")
        assert db.get(models.User, "viewer").role == "Viewer"
        assert {row.access_level for row in db.query(models.BarnAssignment).filter_by(user_id="viewer")} == {"Viewer"}
