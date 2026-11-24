
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
    # Serialize account changes on the Admin rows so concurrent demotions cannot
    # both remove the last active Admin (FOR UPDATE on the production MySQL DB).
    admins = db.query(models.User).filter(
        models.User.role == "Admin"
    ).order_by(models.User.id).populate_existing().with_for_update().all()
    target_user = db.query(models.User).filter(
        models.User.id == user_id
    ).populate_existing().with_for_update().first()

    if not target_user:
        raise HTTPException(404, "User not found")

    next_role = body.role if body.role is not None else target_user.role
    next_status = body.status if body.status is not None else target_user.status
    if next_role not in {"Admin", "Operator", "Viewer"}:
        raise HTTPException(400, "Vai trò không hợp lệ")
    if next_status not in {"active", "locked"}:
        raise HTTPException(400, "Trạng thái tài khoản không hợp lệ")
    if actor_id == user_id and (next_role != "Admin" or next_status != "active"):
        raise HTTPException(400, "Không thể tự hạ vai trò hoặc khóa tài khoản của mình")
    if (target_user.role == "Admin" and target_user.status == "active"
            and (next_role != "Admin" or next_status != "active")
            and not any(admin.id != user_id and admin.status == "active" for admin in admins)):
        raise HTTPException(409, "Phải giữ ít nhất một Quản trị viên đang hoạt động")

    try:
        changed = False
        if target_user.role != next_role:
            assignments = db.query(models.BarnAssignment).filter(
                models.BarnAssignment.user_id == user_id
            ).all()
            for assignment in assignments:
                target = f"barn_assignments:{assignment.barn_id}:{user_id}"
                if next_role == "Admin":
                    # Admin sees every barn; remove explicit grants. A later demotion
                    # requires choosing barns again rather than restoring old grants.
                    db.delete(assignment)
                    record_change(db, actor_id, "barn.assignment.remove", target)
                elif assignment.access_level != next_role:
                    assignment.access_level = next_role
                    record_change(db, actor_id, "barn.assignment.update", target)
            target_user.role = next_role
            changed = True

        if target_user.status != next_status:
            target_user.status = next_status
            changed = True

        if body.full_name is not None and target_user.full_name != body.full_name:
            target_user.full_name = body.full_name
            changed = True

        if changed:
            record_change(db, actor_id, "user.update", f"users:{target_user.id}")
        # Also release the Admin row locks for a no-op update.
        db.commit()
        db.refresh(target_user)
    except Exception:
        db.rollback()
        raise
    return target_user


def reset_password(db: Session, user_id: str, body, actor_id: str):
    if user_id == actor_id:
        raise HTTPException(409, "Đổi mật khẩu của mình trong phần tài khoản cá nhân")
    target_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not target_user:
        raise HTTPException(404, "Không tìm thấy tài khoản")

    try:
        target_user.password_hash = hash_password(body.new_password)
        db.query(models.AuthSession).filter(
            models.AuthSession.user_id == user_id
        ).update({"revoked": 1}, synchronize_session=False)
        record_change(db, actor_id, "user.password_reset", f"users:{user_id}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"message": "Đã đặt lại mật khẩu và thu hồi các phiên làm mới"}
