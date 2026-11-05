"""Alerts (list: everyone signed in; acknowledge: operators) and the alarm (silence: operators; test:
administrators, with the password again). Every control action is audited."""

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..alarm import silence_until, set_silence, silenced_until
from ..db import AdminUser, Alert, as_utc, utcnow
from ..deps import AppState, admin, confirm_password, get_db, get_state, operator, viewer
from ..gallery import ALARM_SILENCED, ALARM_TESTED, ALARM_UNSILENCED, ALERT_ACKNOWLEDGED, audit

router = APIRouter(prefix="/api", tags=["alarm"], dependencies=[Depends(viewer)])

_ID = re.compile(r"^[a-f0-9]{32}$")


class Silence(BaseModel):
    minutes: int = Field(ge=1, le=24 * 60)


class Confirm(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def _alert(a: Alert) -> dict:
    return {"id": a.id, "created_at": as_utc(a.created_at).isoformat(), "kind": a.kind, "camera": a.camera,
            "crossing_id": a.crossing_id, "detail": a.detail, "status": a.status, "alarm": a.alarm,
            "delivery": a.delivery, "acknowledged_by": a.acknowledged_by,
            "acknowledged_at": as_utc(a.acknowledged_at).isoformat() if a.acknowledged_at else None}


def _alarm_status(db: Session, state: AppState) -> dict:
    until = silenced_until(db)
    return {**state.alarm.output_status(), "silenced_until": until.isoformat() if until else None,
            "open_alerts": db.scalar(select(func.count()).select_from(Alert).where(Alert.status == "open")) or 0}


@router.get("/alerts")
def list_alerts(status_: str | None = Query(default=None, alias="status", pattern="^(open|acknowledged)$"),
                limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)) -> dict:
    query = select(Alert)
    if status_:
        query = query.where(Alert.status == status_)
    rows = db.scalars(query.order_by(Alert.created_at.desc(), Alert.id.desc()).limit(limit))
    return {"items": [_alert(a) for a in rows]}


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(operator)) -> dict:
    alert = db.get(Alert, alert_id) if _ID.match(alert_id) else None
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    if alert.status != "acknowledged":
        alert.status, alert.acknowledged_by, alert.acknowledged_at = "acknowledged", user.username, utcnow()
        audit(db, user.username, ALERT_ACKNOWLEDGED, "alert", alert.id)
        db.commit()
    return _alert(alert)


@router.get("/alarm")
def alarm_status(db: Session = Depends(get_db), state: AppState = Depends(get_state)) -> dict:
    return _alarm_status(db, state)


@router.post("/alarm/silence")
async def silence(body: Silence, db: Session = Depends(get_db), user: AdminUser = Depends(operator),
                  state: AppState = Depends(get_state)) -> dict:
    if body.minutes > state.settings.alarm_max_silence_minutes:
        raise HTTPException(422, f"at most {state.settings.alarm_max_silence_minutes} minutes")
    until = silence_until(body.minutes)
    set_silence(db, until, user.username)
    audit(db, user.username, ALARM_SILENCED, "alarm", None, f"{body.minutes} minutes")
    db.commit()
    await state.alarm.stop()  # an output that is on now goes off
    return _alarm_status(db, state)


@router.delete("/alarm/silence")
def unsilence(db: Session = Depends(get_db), user: AdminUser = Depends(operator),
              state: AppState = Depends(get_state)) -> dict:
    set_silence(db, None, user.username)
    audit(db, user.username, ALARM_UNSILENCED, "alarm", None)
    db.commit()
    return _alarm_status(db, state)


@router.post("/alarm/test")
async def test_alarm(body: Confirm, request: Request, db: Session = Depends(get_db), user: AdminUser = Depends(admin),
                     state: AppState = Depends(get_state)) -> dict:
    """Drives the configured output once; in simulation mode nothing is switched."""
    confirm_password(request, state, db, user, body.password, "alarm", "test")
    alert_id = await state.alarm.test(user.username)
    alert = db.get(Alert, alert_id)
    audit(db, user.username, ALARM_TESTED, "alert", alert_id, f"output {state.settings.alarm_output}: "
                                                              f"{alert.alarm if alert else 'unknown'}")
    db.commit()
    return {"alert": _alert(alert) if alert else None, "alarm": _alarm_status(db, state)}
