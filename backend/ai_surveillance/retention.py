"""Retention of gate crossings, alerts and the audit log (hourly, and on demand from the Privacy page).

Face events (frames, crops, rows) and captures have their own loops (face_events.py, captures.py);
run_all() runs those purges too when asked. Each setting is a number of days; 0 keeps the data.
Reference images and embeddings are kept until the person (or the image) is deleted: they are
the gallery, not history. Frigate's own recordings and snapshots follow Frigate's retention
(record.continuous.days, snapshots.retain in its config).
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from .captures import purge_old_captures
from .config import Settings
from .db import Alert, AuditEntry, GateCrossing, utcnow
from .face_events import purge_old_face_events
from .media import MediaStore

log = logging.getLogger(__name__)

CHECK_SECONDS = 3600


def _purge(sessions: sessionmaker, column, days: int) -> int:
    if days <= 0:
        return 0
    with sessions() as db:
        removed = db.execute(delete(column.class_).where(column < utcnow() - timedelta(days=days))).rowcount or 0
        db.commit()
    return removed


def purge_history(sessions: sessionmaker, settings: Settings) -> dict:
    return {
        "gate_crossings": _purge(sessions, GateCrossing.crossed_at, settings.gate_crossing_retention_days),
        "alerts": _purge(sessions, Alert.created_at, settings.alert_retention_days),
        "audit_entries": _purge(sessions, AuditEntry.at, settings.audit_retention_days),
    }


def run_all(sessions: sessionmaker, settings: Settings, store: MediaStore, face_store: MediaStore) -> dict:
    result = purge_history(sessions, settings)
    result["face_events"] = (purge_old_face_events(sessions, face_store, settings.face_event_retention_days)
                             if settings.face_event_retention_days > 0 else 0)
    result["captures"] = (purge_old_captures(sessions, store, settings.capture_retention_days)
                          if settings.capture_retention_days > 0 else 0)
    return result


async def history_retention_loop(sessions: sessionmaker, settings: Settings) -> None:
    while True:
        try:
            removed = await asyncio.to_thread(purge_history, sessions, settings)
            if any(removed.values()):
                log.info("Retention: deleted %s", ", ".join(f"{n} {k}" for k, n in removed.items() if n))
        except Exception:
            log.exception("History retention failed; retrying in an hour")
        await asyncio.sleep(CHECK_SECONDS)
