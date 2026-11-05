from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import AdminUser, utcnow
from ..deps import AppState, client_key, confirm_password, current_user, get_db, get_state
from ..gallery import PASSWORD_CHANGED, audit
from ..security import (MIN_PASSWORD_LENGTH, SESSION_COOKIE, authenticate, create_session, hash_password,
                        revoke_session, revoke_user_sessions)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)


def me_payload(user: AdminUser) -> dict:
    return {"username": user.username, "role": user.role}


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    state: AppState = Depends(get_state),
) -> dict:
    key = client_key(request)
    if state.throttle.is_locked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts. Try again later.")
    user = authenticate(db, body.username, body.password)
    if user is None:
        state.throttle.record_failure(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    state.throttle.reset(key)
    token = create_session(db, user, state.settings.session_ttl_hours)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=state.settings.session_ttl_hours * 3600,
        httponly=True,
        secure=state.settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    return me_payload(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    revoke_session(db, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me")
def me(user: AdminUser = Depends(current_user)) -> dict:
    return me_payload(user)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: PasswordChange, request: Request, db: Session = Depends(get_db),
                    user: AdminUser = Depends(current_user), state: AppState = Depends(get_state)) -> None:
    """Change the signed-in user's own password. The current password is checked with the same
    lockout as sign-in; every other session of this user is signed out, this one stays."""
    confirm_password(request, state, db, user, body.current_password, "user", user.id)
    if body.new_password == body.current_password:
        raise HTTPException(422, "The new password must differ from the current one")
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = utcnow()
    revoke_user_sessions(db, user.id, keep_token=request.cookies.get(SESSION_COOKIE))
    audit(db, user.username, PASSWORD_CHANGED, "user", user.id)
    db.commit()
