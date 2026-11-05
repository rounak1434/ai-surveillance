"""Gate lines (administrators) and gate crossings (everyone signed in; names and images by role)."""

import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, StrictBool, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import ROLE_OPERATOR, AdminUser, GateCrossing, GateLine, Person, as_utc, utcnow
from ..deps import AppState, admin, confirm_password, get_db, get_state, known_camera, viewer
from ..gallery import GATE_LINE_DELETED, GATE_LINE_SAVED, audit
from ..gate import VERDICTS
from ..security import has_role

router = APIRouter(prefix="/api/gate", tags=["gate"], dependencies=[Depends(viewer)])

_ID = re.compile(r"^[a-f0-9]{32}$")
Fraction = Field(ge=0.0, le=1.0)


class LineInput(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[^\x00-\x1f\x7f]+$")
    x1: float = Fraction
    y1: float = Fraction
    x2: float = Fraction
    y2: float = Fraction
    in_side: str = Field(pattern="^(left|right)$")
    record_exits: StrictBool = True
    enabled: StrictBool = True
    alarm_on_unauthorized: StrictBool = False
    cooldown_seconds: int = Field(default=10, ge=0, le=3600)
    password: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def _long_enough(self) -> "LineInput":
        if ((self.x2 - self.x1) ** 2 + (self.y2 - self.y1) ** 2) ** 0.5 < 0.05:
            raise ValueError("the line must be at least 5% of the frame long")
        return self


class Confirm(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def _line(row: GateLine) -> dict:
    return {"id": row.id, "camera": row.camera, "name": row.name,
            "p1": {"x": row.x1, "y": row.y1}, "p2": {"x": row.x2, "y": row.y2}, "in_side": row.in_side,
            "record_exits": row.record_exits, "enabled": row.enabled,
            "alarm_on_unauthorized": row.alarm_on_unauthorized, "cooldown_seconds": row.cooldown_seconds,
            "updated_by": row.updated_by, "updated_at": as_utc(row.updated_at).isoformat()}


def _crossing(c: GateCrossing, names: dict[str, str], detailed: bool) -> dict:
    body = {"id": c.id, "line_id": c.line_id, "camera": c.camera, "frigate_event_id": c.frigate_event_id,
            "sequence": c.sequence, "direction": c.direction, "crossed_at": as_utc(c.crossed_at).isoformat(),
            "point": {"x": c.point_x, "y": c.point_y}, "verdict": c.verdict, "reason": c.reason,
            "checked_at": as_utc(c.checked_at).isoformat() if c.checked_at else None}
    if detailed:  # operators and administrators: who matched and where the images are
        body.update({"outcome": c.outcome, "similarity": c.similarity,
                     "person": {"id": c.person_id, "display_name": names.get(c.person_id)} if c.person_id else None,
                     "face_event_id": c.face_event_id})
    return body


def gate_status(state: AppState) -> dict:
    mqtt = state.mqtt
    return {"tracking": state.gate is not None,
            "mqtt": mqtt.as_dict() if mqtt is not None else {"enabled": False, "connected": False},
            "note": None if state.gate is not None else
            "Gate lines need MQTT event updates from Frigate (MQTT_ENABLED=true and Frigate's mqtt section); "
            "lines are saved but no crossings are counted until then."}


@router.get("/lines")
def list_lines(db: Session = Depends(get_db), state: AppState = Depends(get_state)) -> dict:
    return {"items": [_line(r) for r in db.scalars(select(GateLine).order_by(GateLine.camera))],
            "status": gate_status(state)}


@router.put("/lines/{camera}")
def save_line(body: LineInput, request: Request, camera: str = Depends(known_camera), db: Session = Depends(get_db),
              user: AdminUser = Depends(admin), state: AppState = Depends(get_state)) -> dict:
    """Create or replace the camera's line. Needs the password again: the line can drive the alarm."""
    confirm_password(request, state, db, user, body.password, "gate_line", camera)
    row = db.scalar(select(GateLine).where(GateLine.camera == camera))
    if row is None:
        row = GateLine(camera=camera)
        db.add(row)
    for name in ("name", "x1", "y1", "x2", "y2", "in_side", "record_exits", "enabled", "alarm_on_unauthorized",
                 "cooldown_seconds"):
        setattr(row, name, getattr(body, name))
    row.updated_by, row.updated_at = user.username, utcnow()
    db.flush()
    audit(db, user.username, GATE_LINE_SAVED, "gate_line", row.id,
          f"camera {camera}; in side {body.in_side}; exits {body.record_exits}; enabled {body.enabled}; "
          f"alarm {body.alarm_on_unauthorized}; cooldown {body.cooldown_seconds}s")
    db.commit()
    if state.gate is not None:
        state.gate.reload()
    return _line(row)


@router.delete("/lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_line(line_id: str, body: Confirm, request: Request, db: Session = Depends(get_db),
                user: AdminUser = Depends(admin), state: AppState = Depends(get_state)) -> None:
    """Deletes the line and its crossings (alerts keep their record, without the link)."""
    row = db.get(GateLine, line_id) if _ID.match(line_id) else None
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gate line not found")
    confirm_password(request, state, db, user, body.password, "gate_line", row.id)
    audit(db, user.username, GATE_LINE_DELETED, "gate_line", row.id, f"camera {row.camera}")
    db.delete(row)
    db.commit()
    if state.gate is not None:
        state.gate.reload()


@router.get("/crossings")
def list_crossings(camera: str | None = Query(default=None, max_length=64),
                   verdict: str | None = None, direction: str | None = Query(default=None, pattern="^(in|out)$"),
                   since: datetime | None = None, limit: int = Query(default=50, ge=1, le=200),
                   before: datetime | None = Query(default=None, description="crossed before (paging)"),
                   db: Session = Depends(get_db), user: AdminUser = Depends(viewer)) -> dict:
    if verdict is not None and verdict not in VERDICTS:
        raise HTTPException(422, f"verdict must be one of: {', '.join(sorted(VERDICTS))}")
    query = select(GateCrossing)
    if camera:
        query = query.where(GateCrossing.camera == camera)
    if verdict:
        query = query.where(GateCrossing.verdict == verdict)
    if direction:
        query = query.where(GateCrossing.direction == direction)
    if since:
        query = query.where(GateCrossing.crossed_at >= (since if since.tzinfo else since.replace(tzinfo=UTC)))
    if before:
        query = query.where(GateCrossing.crossed_at < (before if before.tzinfo else before.replace(tzinfo=UTC)))
    rows = list(db.scalars(query.order_by(GateCrossing.crossed_at.desc(), GateCrossing.id.desc()).limit(limit)))
    detailed = has_role(user, ROLE_OPERATOR)
    ids = {r.person_id for r in rows if r.person_id}
    names = dict(db.execute(select(Person.id, Person.display_name).where(Person.id.in_(ids))).all()) \
        if ids and detailed else {}
    return {"items": [_crossing(r, names, detailed) for r in rows]}
