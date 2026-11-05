"""Accounts and roles (administrators only).

Roles: viewer (live view, crossings and alerts without names or images), operator (also face events,
images, footage, people records, acknowledging alerts, silencing the alarm, captures), admin
(also enrollment, recognition, gate lines, alarm tests, devices, accounts, privacy actions).

Every change is audited and needs the acting administrator's password again. The last active
administrator can never be removed, disabled or demoted, so the system cannot lock itself out;
if every administrator password is lost, `ai-surveillance create-admin` on the host recovers access.
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import ROLE_ADMIN, ROLES, AdminUser, as_utc, utcnow
from ..deps import AppState, admin, confirm_password, get_db, get_state
from ..gallery import PASSWORD_RESET, USER_CREATED, USER_DELETED, USER_UPDATED, audit
from ..security import MIN_PASSWORD_LENGTH, hash_password, revoke_user_sessions

router = APIRouter(prefix="/api/users", tags=["users"], dependencies=[Depends(admin)])

_ID = re.compile(r"^[a-f0-9]{32}$")
_USERNAME = r"^[A-Za-z0-9._-]{3,64}$"


class Confirmed(BaseModel):
    password: str = Field(min_length=1, max_length=256)  # the acting administrator's own password


class UserCreate(Confirmed):
    username: str = Field(pattern=_USERNAME)
    role: str = Field(pattern="^(admin|operator|viewer)$")
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)


class UserUpdate(Confirmed):
    role: str | None = Field(default=None, pattern="^(admin|operator|viewer)$")
    disabled: StrictBool | None = None


class PasswordReset(Confirmed):
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)


def _user(u: AdminUser) -> dict:
    return {"id": u.id, "username": u.username, "role": u.role, "disabled": u.disabled,
            "created_at": as_utc(u.created_at).isoformat(),
            "password_changed_at": as_utc(u.password_changed_at).isoformat() if u.password_changed_at else None}


def _get(db: Session, user_id: str) -> AdminUser:
    user = db.get(AdminUser, user_id) if _ID.match(user_id) else None
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


def _active_admins(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(AdminUser)
                     .where(AdminUser.role == ROLE_ADMIN, AdminUser.disabled.is_(False))) or 0


@router.get("")
def list_users(db: Session = Depends(get_db)) -> dict:
    return {"items": [_user(u) for u in db.scalars(select(AdminUser).order_by(func.lower(AdminUser.username)))],
            "roles": list(ROLES)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, request: Request, db: Session = Depends(get_db), me: AdminUser = Depends(admin),
                state: AppState = Depends(get_state)) -> dict:
    confirm_password(request, state, db, me, body.password, "user", "new")
    if db.scalar(select(AdminUser).where(func.lower(AdminUser.username) == body.username.lower())):
        raise HTTPException(409, "That username is taken")
    user = AdminUser(username=body.username, role=body.role, password_hash=hash_password(body.new_password),
                     password_changed_at=utcnow())
    db.add(user)
    db.flush()
    audit(db, me.username, USER_CREATED, "user", user.id, f"role {body.role}")
    db.commit()
    return _user(user)


@router.patch("/{user_id}")
def update_user(user_id: str, body: UserUpdate, request: Request, db: Session = Depends(get_db),
                me: AdminUser = Depends(admin), state: AppState = Depends(get_state)) -> dict:
    user = _get(db, user_id)
    confirm_password(request, state, db, me, body.password, "user", user.id)
    loses_admin = user.role == ROLE_ADMIN and not user.disabled and (
        (body.role is not None and body.role != ROLE_ADMIN) or body.disabled is True)
    if loses_admin and _active_admins(db) <= 1:
        raise HTTPException(409, "This is the last active administrator; add another administrator first")
    if user.id == me.id and body.disabled:
        raise HTTPException(409, "You cannot disable your own account")
    changed = []
    if body.role is not None and body.role != user.role:
        changed.append(f"role {user.role} -> {body.role}")
        user.role = body.role
    if body.disabled is not None and body.disabled != user.disabled:
        changed.append("disabled" if body.disabled else "enabled")
        user.disabled = body.disabled
    if changed:
        revoke_user_sessions(db, user.id)  # new rights apply from the next sign-in
        audit(db, me.username, USER_UPDATED, "user", user.id, "; ".join(changed))
        db.commit()
    return _user(user)


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(user_id: str, body: PasswordReset, request: Request, db: Session = Depends(get_db),
                   me: AdminUser = Depends(admin), state: AppState = Depends(get_state)) -> None:
    user = _get(db, user_id)
    confirm_password(request, state, db, me, body.password, "user", user.id)
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = utcnow()
    revoke_user_sessions(db, user.id)
    audit(db, me.username, PASSWORD_RESET, "user", user.id)
    db.commit()


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: str, body: Confirmed, request: Request, db: Session = Depends(get_db),
                me: AdminUser = Depends(admin), state: AppState = Depends(get_state)) -> None:
    user = _get(db, user_id)
    confirm_password(request, state, db, me, body.password, "user", user.id)
    if user.id == me.id:
        raise HTTPException(409, "You cannot delete your own account")
    if user.role == ROLE_ADMIN and not user.disabled and _active_admins(db) <= 1:
        raise HTTPException(409, "This is the last active administrator")
    audit(db, me.username, USER_DELETED, "user", user.id)
    db.delete(user)  # sessions cascade
    db.commit()
