
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from .auth import hash_password
from .audit import record_change


def get_users(db: Session):
    return db.query(models.User).order_by(
        models.User.username
    ).all()


def create_user(db: Session, body, actor_id: str | None = None):
    existing_user = db.query(models.User).filter(
        models.User.username == body.username
    ).first()

    if existing_user:
        raise HTTPException(409, "Username already exists")

    new_user = models.User(
        id=str(__import__("uuid").uuid4()),
        username=body.username,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        status="active"
    )

    db.add(new_user)
    record_change(db, actor_id, "user.create", f"users:{new_user.id}")

    try:
        db.commit()
        db.refresh(new_user)
    except Exception:
        db.rollback()
        raise

    return new_user


def update_user(db: Session, user_id: str, body, actor_id: str | None = None):
    target_user = db.query(models.User).filter(
        models.User.id == user_id
    ).first()

    if not target_user:
        raise HTTPException(404, "User not found")

    changed = False
    if body.role is not None and target_user.role != body.role:
        if body.role not in ["Admin", "Operator", "Viewer"]:
            raise HTTPException(400, "Invalid role")

        target_user.role = body.role
        changed = True

    if body.status is not None and target_user.status != body.status:
        if body.status not in ["active", "locked"]:
            raise HTTPException(400, "Invalid account status")

        target_user.status = body.status
        changed = True

    if body.full_name is not None and target_user.full_name != body.full_name:
        target_user.full_name = body.full_name
        changed = True

    if changed:
        record_change(db, actor_id, "user.update", f"users:{target_user.id}")
        db.commit()
        db.refresh(target_user)
    return target_user
