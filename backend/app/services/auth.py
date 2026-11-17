
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import uuid

import bcrypt
import jwt
from jwt.exceptions import InvalidTokenError

from fastapi import HTTPException
from sqlalchemy.orm import Session



from ..models import User, AuthSession
from pathlib import Path

from .. import models

from ..database import ENV_FILE as ENV_PATH  # deployment/.env (or IOT_ENV_FILE)
from .audit import record_change

if ENV_PATH.exists():
    with open(ENV_PATH, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))


def _secret_key() -> str:
    # Checked on use, not at import, so the app imports without JWT config.
    if not SECRET_KEY:
        raise RuntimeError("JWT_SECRET_KEY environment variable is missing")
    return SECRET_KEY


# PASSWORD ------------------------------------------------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            hashed.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


# JWT -----------------------------------------------------

def create_token(
    user_id: str,
    token_type: str,
    expires_delta: timedelta
):
    now = datetime.now(timezone.utc)
    jti = str(uuid.uuid4())

    payload = {
        "sub": str(user_id),
        "type": token_type,
        "jti": jti,
        "iat": now,
        "exp": now + expires_delta
    }

    token = jwt.encode(
        payload,
        _secret_key(),
        algorithm=ALGORITHM
    )

    return token, jti


def decode_token(token: str):
    try:
        return jwt.decode(
            token,
            _secret_key(),
            algorithms=[ALGORITHM]
        )

    except InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )

def get_current_user(db: Session, token: str):
    payload = decode_token(token)

    if payload.get("type") != "access":
        raise HTTPException(401, "Invalid access token")

    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(401, "Invalid access token")

    current_user = db.query(models.User).filter(
        models.User.id == user_id
    ).first()

    if not current_user or current_user.status != "active":
        raise HTTPException(401, "Account unavailable")

    return current_user


# REFRESH SESSION ----------------------------------------

def get_refresh_session(token: str, db: Session):
    payload = decode_token(token)

    if payload.get("type") != "refresh":
        raise HTTPException(401, "Invalid refresh token")

    jti = payload.get("jti")
    user_id = payload.get("sub")

    if not jti or not user_id:
        raise HTTPException(401, "Invalid refresh token")

    session = db.query(models.AuthSession).filter(
        models.AuthSession.jti == jti,
        models.AuthSession.user_id == user_id
    ).first()

    if (
        not session
        or session.revoked
        or session.expires_at <= datetime.utcnow()
    ):
        raise HTTPException(
            401,
            "Refresh token revoked or expired"
        )

    return session, user_id


# LOGIN ---------------------------------------------------

def login(db: Session, body):
    current_user = db.query(models.User).filter(
        models.User.username == body.username
    ).first()

    if (
        not current_user
        or not verify_password(
            body.password,
            current_user.password_hash
        )
    ):
        raise HTTPException(
            401,
            "Invalid username or password"
        )

    if current_user.status != "active":
        raise HTTPException(403, "Account is locked")

    access_token, _ = create_token(
        current_user.id,
        "access",
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    refresh_token, jti = create_token(
        current_user.id,
        "refresh",
        timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )

    db.add(models.AuthSession(
        jti=jti,
        user_id=current_user.id,
        expires_at=datetime.utcnow() + timedelta(
            days=REFRESH_TOKEN_EXPIRE_DAYS
        ),
        revoked=0
    ))
    record_change(db, current_user.id, "auth.login", f"users:{current_user.id}")

    db.commit()

    return {
        "message": "Login successful",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": {
            "id": current_user.id,
            "username": current_user.username,
            "full_name": current_user.full_name,
            "role": current_user.role
        }
    }


# REFRESH TOKEN ------------------------------------------

def refresh_token(db: Session, body):
    session, user_id = get_refresh_session(
        body.refresh_token,
        db
    )

    current_user = db.query(models.User).filter(
        models.User.id == user_id
    ).first()

    if not current_user or current_user.status != "active":
        raise HTTPException(401, "Account unavailable")

    # Revoke old refresh token
    session.revoked = 1

    access_token, _ = create_token(
        user_id,
        "access",
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    new_refresh_token, new_jti = create_token(
        user_id,
        "refresh",
        timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )

    db.add(models.AuthSession(
        jti=new_jti,
        user_id=user_id,
        expires_at=datetime.utcnow() + timedelta(
            days=REFRESH_TOKEN_EXPIRE_DAYS
        ),
        revoked=0
    ))
    record_change(db, user_id, "auth.refresh", f"users:{user_id}")

    db.commit()

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }


# LOGOUT --------------------------------------------------

def logout(db: Session, refresh_token_value: str, current_user):
    session, user_id = get_refresh_session(
        refresh_token_value,
        db
    )

    if user_id != current_user.id:
        raise HTTPException(403, "Invalid session owner")

    session.revoked = 1
    record_change(db, current_user.id, "auth.logout", f"auth_sessions:{session.jti}")
    db.commit()

    return {"message": "Logged out successfully"}


# CHANGE PASSWORD ----------------------------------------

def change_password(db: Session, body, current_user):
    if not verify_password(
        body.old_password,
        current_user.password_hash
    ):
        raise HTTPException(400, "Incorrect old password")

    current_user.password_hash = hash_password(
        body.new_password
    )

    # Revoke all refresh tokens after password change
    db.query(models.AuthSession).filter(
        models.AuthSession.user_id == current_user.id
    ).update(
        {"revoked": 1},
        synchronize_session=False
    )

    record_change(
        db,
        current_user.id,
        "auth.password.change",
        f"users:{current_user.id}"
    )
    db.commit()

    return {"message": "Password changed successfully"}
