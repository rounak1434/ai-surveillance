"""Event footage: the Frigate recording around a face event or a gate crossing (operators).

The clip covers [start - EVENT_CLIP_PRE_SECONDS, end + EVENT_CLIP_POST_SECONDS], at most
EVENT_CLIP_MAX_SECONDS from its start. It is exported by Frigate and copied into the captures like an
operator clip (captures.py), so it is served only through /api/captures/<id>/file behind sign-in and
role checks, never from Frigate directly. One clip per event: asking again returns the pending or
ready one; a failed one is retried. Footage older than FRIGATE_RECORDING_DAYS is reported as expired
(410) without asking Frigate; any other gap shows Frigate's answer on the capture. Requests and
views are audited.
"""

import re
import time

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..captures import InsufficientStorage, check_free_space, run_clip_export
from ..db import AdminUser, Capture, FaceEvent, GateCrossing, as_utc
from ..deps import AppState, get_db, get_state, operator
from ..gallery import FOOTAGE_REQUESTED, audit
from .captures import _to_dict

router = APIRouter(prefix="/api/footage", tags=["footage"], dependencies=[Depends(operator)])

_ID = re.compile(r"^[a-f0-9]{32}$")


def _range(state: AppState, start: float, end: float) -> tuple[float, float]:
    s = state.settings
    clip_start = start - s.event_clip_pre_seconds
    clip_end = min(end + s.event_clip_post_seconds, clip_start + s.event_clip_max_seconds)
    return clip_start, max(clip_end, clip_start + 1)


def _request(db: Session, state: AppState, user: AdminUser, kind: str, item_id: str, camera: str,
             start: float, end: float):
    settings = state.settings
    source = f"{kind}:{item_id}"
    clip_start, clip_end = _range(state, start, end)
    days = settings.frigate_recording_days
    if days > 0 and clip_end < time.time() - days * 86400:
        return JSONResponse({"error": "footage_expired",
                             "detail": f"Frigate keeps recordings for {days} days; this footage has expired."},
                            status_code=status.HTTP_410_GONE)
    existing = db.scalar(select(Capture).where(Capture.source == source, Capture.status != "failed")
                         .order_by(Capture.created_at.desc()))
    if existing is not None:
        return _to_dict(existing)
    try:
        check_free_space(state.store, settings)
    except InsufficientStorage as exc:
        raise HTTPException(status.HTTP_507_INSUFFICIENT_STORAGE, str(exc)) from exc
    capture = Capture(camera=camera, kind="clip", status="pending", source=source, clip_start=clip_start,
                      clip_end=clip_end, duration_seconds=int(round(clip_end - clip_start)))
    db.add(capture)
    db.flush()
    audit(db, user.username, FOOTAGE_REQUESTED, kind, item_id, f"capture {capture.id}")
    db.commit()
    state.spawn(run_clip_export(capture.id, int(time.time()), settings, state.frigate, state.store,
                                state.db.sessionmaker))
    return JSONResponse(_to_dict(capture), status_code=status.HTTP_202_ACCEPTED)


@router.post("/face-events/{event_id}")
def face_event_footage(event_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(operator),
                       state: AppState = Depends(get_state)):
    event = db.get(FaceEvent, event_id) if _ID.match(event_id) else None
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Face event not found")
    return _request(db, state, user, "face_event", event.id, event.camera,
                    as_utc(event.started_at).timestamp(), as_utc(event.ended_at).timestamp())


@router.post("/crossings/{crossing_id}")
def crossing_footage(crossing_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(operator),
                     state: AppState = Depends(get_state)):
    crossing = db.get(GateCrossing, crossing_id) if _ID.match(crossing_id) else None
    if crossing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gate crossing not found")
    return _request(db, state, user, "crossing", crossing.id, crossing.camera, crossing.frame_time,
                    crossing.frame_time)
