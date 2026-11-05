"""Privacy: retention overview, purge now, delete all reference embeddings (administrators);
capabilities of the optional estimators (everyone signed in)."""

import asyncio

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import recognition
from ..attributes import capabilities
from ..db import (AdminUser, Alert, AuditEntry, Capture, FaceEvent, GateCrossing, Person, ReferenceFace)
from ..deps import AppState, admin, confirm_password, get_db, get_state, viewer
from ..gallery import EMBEDDINGS_PURGED, RECOGNITION_DISABLED, RETENTION_RUN, audit
from ..retention import run_all

router = APIRouter(prefix="/api", tags=["privacy"])


class Confirm(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def _count(db: Session, model, *where) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


@router.get("/capabilities", dependencies=[Depends(viewer)])
async def get_capabilities(state: AppState = Depends(get_state)) -> dict:
    return await capabilities(state.inference)


@router.get("/privacy", dependencies=[Depends(admin)])
def privacy(db: Session = Depends(get_db), state: AppState = Depends(get_state)) -> dict:
    s = state.settings
    return {
        "retention_days": {  # 0 = kept until deleted by hand
            "face_events": s.face_event_retention_days, "captures": s.capture_retention_days,
            "gate_crossings": s.gate_crossing_retention_days, "alerts": s.alert_retention_days,
            "audit_log": s.audit_retention_days, "frigate_recordings": s.frigate_recording_days,
        },
        "counts": {
            "people": _count(db, Person), "reference_images": _count(db, ReferenceFace),
            "reference_embeddings": _count(db, ReferenceFace, ReferenceFace.embedding_enc.is_not(None)),
            "face_events": _count(db, FaceEvent), "gate_crossings": _count(db, GateCrossing),
            "alerts": _count(db, Alert), "captures": _count(db, Capture), "audit_entries": _count(db, AuditEntry),
        },
        "encryption": {
            "biometric_data": "Reference images and embeddings: AES-256-GCM with the credentials key.",
            "key_source": "CREDENTIALS_KEY (environment)" if s.credentials_key else "key file (CREDENTIALS_KEY_FILE)",
            "not_encrypted": "Face-event frames and crops, captures and Frigate recordings are plain files: "
                             "use full-disk encryption on the host.",
        },
        "recognition_enabled": recognition.is_enabled(db),
    }


@router.post("/privacy/retention/run")
async def run_retention(body: Confirm, request: Request, db: Session = Depends(get_db),
                        user: AdminUser = Depends(admin), state: AppState = Depends(get_state)) -> dict:
    confirm_password(request, state, db, user, body.password, "privacy", "retention")
    result = await asyncio.to_thread(run_all, state.db.sessionmaker, state.settings, state.store, state.face_store)
    audit(db, user.username, RETENTION_RUN, "privacy", None, ", ".join(f"{k} {v}" for k, v in result.items()))
    db.commit()
    return {"deleted": result}


@router.post("/privacy/embeddings/purge")
def purge_embeddings(body: Confirm, request: Request, db: Session = Depends(get_db), user: AdminUser = Depends(admin),
                     state: AppState = Depends(get_state)) -> dict:
    """Delete every stored reference embedding and switch recognition off (otherwise they would be
    computed again at the next poll). Reference images stay; switching recognition on again
    recomputes the embeddings from them."""
    confirm_password(request, state, db, user, body.password, "privacy", "embeddings")
    removed = db.execute(update(ReferenceFace).where(ReferenceFace.embedding_enc.is_not(None))
                         .values(embedding_enc=None, embedder=None)).rowcount or 0
    was_on = recognition.is_enabled(db)
    if was_on:
        recognition.set_enabled(db, False, user.username)
        audit(db, user.username, RECOGNITION_DISABLED, "setting", "recognition", "with the embedding purge")
    audit(db, user.username, EMBEDDINGS_PURGED, "privacy", None, f"{removed} embedding(s)")
    db.commit()
    return {"deleted_embeddings": removed, "recognition_switched_off": was_on}
