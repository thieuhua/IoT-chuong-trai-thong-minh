
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from .audit import record_change


def get_barns(db: Session, current_user):
    if current_user.role == "Admin":
        return db.query(models.Barn).all()

    if current_user.role in ["Operator", "Viewer"]:
        return db.query(models.Barn).join(
            models.BarnAssignment,
            models.BarnAssignment.barn_id == models.Barn.id
        ).filter(
            models.BarnAssignment.user_id == current_user.id
        ).all()

    raise HTTPException(403, "Permission denied")


def get_barn_devices(db: Session, barn_id: str):
    return db.query(models.Device).filter(
        models.Device.barn_id == barn_id
    ).order_by(models.Device.name.asc()).all()


def get_barn_assignments(db: Session, barn_id: str):
    return db.query(models.BarnAssignment).filter(
        models.BarnAssignment.barn_id == barn_id
    ).order_by(models.BarnAssignment.user_id.asc()).all()


def get_barn_users(db: Session, barn_id: str):
    return db.query(models.User).join(
        models.BarnAssignment,
        models.BarnAssignment.user_id == models.User.id
    ).filter(
        models.BarnAssignment.barn_id == barn_id
    ).order_by(models.User.username.asc()).all()


def create_barn(db: Session, body, actor_id: str | None = None):
    new_barn = models.Barn(
        id=str(uuid.uuid4()),
        name=body.name,
        zone=body.zone,
        animal_type=body.animal_type
    )

    db.add(new_barn)
    record_change(db, actor_id, "barn.create", f"barns:{new_barn.id}")

    try:
        db.commit()
        db.refresh(new_barn)
    except Exception:
        db.rollback()
        raise

    return new_barn


def assign_users(
    db: Session,
    barn_id: str,
    body,
    actor_id: str | None = None
):
    target_barn = db.query(models.Barn).filter(
        models.Barn.id == barn_id
    ).first()

    if not target_barn:
        raise HTTPException(404, "Barn not found")

    for item in body.assignments:
        target_user = db.query(models.User).filter(
            models.User.id == item.user_id
        ).first()

        if not target_user:
            raise HTTPException(404, "User not found")

        if target_user.role not in ["Operator", "Viewer"]:
            raise HTTPException(
                400,
                "Only Operator or Viewer can be assigned to a barn"
            )

        if item.access_level not in ["Operator", "Viewer"]:
            raise HTTPException(400, "Invalid access level")

        if target_user.role != item.access_level:
            raise HTTPException(
                400,
                "Access level must match the user's role"
            )

    try:
        for item in body.assignments:
            assignment = db.query(models.BarnAssignment).filter(
                models.BarnAssignment.user_id == item.user_id,
                models.BarnAssignment.barn_id == barn_id
            ).first()

            changed = assignment is None or assignment.access_level != item.access_level
            if assignment:
                assignment.access_level = item.access_level
            else:
                assignment = models.BarnAssignment(
                    user_id=item.user_id,
                    barn_id=barn_id,
                    access_level=item.access_level
                )
                db.add(assignment)

            if changed:
                record_change(
                    db, actor_id, "barn.assignment.update",
                    f"barn_assignments:{barn_id}:{item.user_id}"
                )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "message": "Users assigned successfully",
        "barn_id": barn_id,
        "assignments": [
            {"user_id": item.user_id, "access_level": item.access_level}
            for item in body.assignments
        ]
    }


def remove_user_assignment(
    db: Session,
    barn_id: str,
    user_id: str,
    actor_id: str | None = None
):
    target_barn = db.query(models.Barn).filter(
        models.Barn.id == barn_id
    ).first()

    if not target_barn:
        raise HTTPException(404, "Barn not found")

    target_user = db.query(models.User).filter(
        models.User.id == user_id
    ).first()

    if not target_user:
        raise HTTPException(404, "User not found")

    assignment = db.query(models.BarnAssignment).filter(
        models.BarnAssignment.barn_id == barn_id,
        models.BarnAssignment.user_id == user_id
    ).first()

    if not assignment:
        raise HTTPException(404, "User is not assigned to this barn")

    db.delete(assignment)
    record_change(
        db,
        actor_id,
        "barn.assignment.remove",
        f"barn_assignments:{barn_id}:{user_id}"
    )
    db.commit()

    return {
        "message": "User unassigned successfully",
        "barn_id": barn_id,
        "user_id": user_id
    }
