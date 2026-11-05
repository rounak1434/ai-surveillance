"""FastAPI application factory."""

import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from .alarm import AlarmService
from .captures import fail_stale_pending, retention_loop
from .config import Settings, get_settings
from .credentials import CredentialCipher, load_key
from .db import Database
from .deps import AppState
from .face_events import Ingestor, face_ingest_loop, face_retention_loop
from .frigate_client import FrigateClient
from .gate import GateService
from .media import MediaStore
from .inference_client import InferenceClient
from .mqtt_events import MqttStatus, mqtt_loop
from .retention import history_retention_loop
from .routes import (alarm, analysis, audit, auth, cameras, captures, devices, face_events, footage, frigate, gate,
                     health, live, people, privacy, recognition, users)
from .security import LoginThrottle, purge_expired_sessions

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, frigate_transport: httpx.AsyncBaseTransport | None = None,
               alarm_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.database_url)
        db.migrate()
        stale = fail_stale_pending(db.sessionmaker)
        if stale:
            log.info("Marked %d interrupted capture(s) as failed", stale)
        with db.sessionmaker() as session:
            purge_expired_sessions(session)
        store = MediaStore(settings.media_root)
        partials = store.remove_partials()
        if partials:
            log.info("Removed %d partial capture file(s) left by a restart", partials)
        face_store = MediaStore(settings.media_root, "faces")
        face_store.remove_partials()
        gallery_store = MediaStore(settings.media_root, "gallery")
        gallery_store.remove_partials()
        app.state.app = AppState(
            settings=settings,
            db=db,
            frigate=FrigateClient(settings, transport=frigate_transport),
            store=store,
            throttle=LoginThrottle(settings.login_max_failures, settings.login_lockout_seconds),
            cipher=CredentialCipher(load_key(settings)),
            inference=InferenceClient(settings),
            analysis_slots=asyncio.Semaphore(settings.analysis_concurrency),
            face_store=face_store,
            gallery_store=gallery_store,
        )
        state: AppState = app.state.app
        state.alarm = AlarmService(settings, db.sessionmaker, transport=alarm_transport)
        # The ingestor also serves the gate's immediate face checks, so it exists even when the
        # face-event loop is switched off.
        state.ingestor = Ingestor(settings, state.frigate, state.inference, db.sessionmaker, face_store,
                                  cipher=state.cipher, gallery_store=gallery_store)
        wake = asyncio.Event() if settings.mqtt_enabled else None
        if settings.mqtt_enabled:
            state.mqtt = MqttStatus()
            state.gate = GateService(settings, db.sessionmaker, state)
            state.spawn(mqtt_loop(settings, state.mqtt, state.gate, wake if settings.face_events_enabled else None))
        if settings.capture_retention_days > 0:
            state.spawn(retention_loop(db.sessionmaker, store, settings.capture_retention_days))
        if settings.face_events_enabled:
            state.spawn(face_ingest_loop(state.ingestor, wake, state.mqtt))
        if settings.face_event_retention_days > 0:
            state.spawn(face_retention_loop(db.sessionmaker, face_store, settings.face_event_retention_days))
        state.spawn(history_retention_loop(db.sessionmaker, settings))
        yield
        for task in list(state.background):
            task.cancel()
        await state.alarm.aclose()
        await state.frigate.aclose()
        await state.inference.aclose()
        db.engine.dispose()

    app = FastAPI(title=f"{settings.app_display_name} API", lifespan=lifespan, docs_url=None, redoc_url=None)
    for module in (health, auth, users, cameras, captures, footage, devices, frigate, face_events, gate, alarm, people,
                   recognition, audit, privacy, analysis, live):
        app.include_router(module.router)
    return app


def app() -> FastAPI:
    """Entry point for `uvicorn --factory ai_surveillance.main:app`."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()
