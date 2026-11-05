"""Alerts and the alarm output.

Alerts are always recorded in the database (the Alerts page). They are raised for gate entries:
  unauthorized_entry   verdict UNAUTHORIZED (gate.py: one clear, good-quality face that does not
                       match a non-empty gallery)
  needs_review         verdict NEEDS_REVIEW (uncertain match, poor quality, no face, ...): an operator
                       looks at it; never an alarm
  alarm_test           a manual test by an administrator
Optionally each alert is POSTed as JSON to ALERT_WEBHOOK_URL (a LAN address; ids, camera and
reason only: no names, images or embeddings).

The alarm output fires only for unauthorized_entry on a line with "alarm on unauthorized" switched
on, and for tests. Outputs (ALARM_OUTPUT):
  simulation  (default) nothing is switched; the alert records "simulated"
  http_relay  a network relay on the LAN: ALARM_RELAY_ON_URL, then ALARM_RELAY_OFF_URL after
              ALARM_DURATION_SECONDS (or when silenced). The address must be an IP literal inside
              DEVICE_ALLOWED_NETWORKS; anything else is refused and recorded as "failed".
  none        alerts only
A physical output is therefore never driven unless an administrator configured it in .env. While
silenced (operators, at most ALARM_MAX_SILENCE_MINUTES) or within ALARM_COOLDOWN_SECONDS of the last
activation, alerts are still recorded but the output is not driven.
"""

import asyncio
import ipaddress
import json
import logging
import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .db import Alert, AppSetting, as_utc, utcnow
from .netguard import AddressNotAllowed, check_ip, parse_networks

log = logging.getLogger(__name__)

UNAUTHORIZED_ENTRY = "unauthorized_entry"
NEEDS_REVIEW = "needs_review"
ALARM_TEST = "alarm_test"

# Alert.alarm
NONE, SIMULATED, ACTIVATED, FAILED, SILENCED, COOLDOWN, DISABLED = (
    "none", "simulated", "activated", "failed", "silenced", "cooldown", "disabled")

_SILENCE_KEY = "alarm_silenced_until"


class OutputRefused(Exception):
    pass


def lan_url(url: str, settings: Settings) -> str:
    """Validate an output/webhook URL: http(s), an IP literal inside the allowed device networks."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise OutputRefused("the URL must start with http:// or https://")
    try:
        ip = ipaddress.ip_address(parts.hostname)
    except ValueError:
        raise OutputRefused("the URL must use an IP address, not a host name") from None
    try:
        check_ip(ip, parse_networks(settings.device_allowed_networks))
    except AddressNotAllowed as exc:
        raise OutputRefused(str(exc)) from None
    return url


def silenced_until(db: Session) -> datetime | None:
    row = db.get(AppSetting, _SILENCE_KEY)
    if row is None:
        return None
    try:
        value = json.loads(row.value)
        until = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None
    if until is None or as_utc(until) <= utcnow():
        return None
    return as_utc(until)


def set_silence(db: Session, until: datetime | None, username: str) -> None:
    """In the caller's transaction."""
    row = db.get(AppSetting, _SILENCE_KEY)
    if row is None:
        row = AppSetting(key=_SILENCE_KEY)
        db.add(row)
    row.value, row.updated_at, row.updated_by = json.dumps(until.isoformat() if until else None), utcnow(), username


class AlarmService:
    def __init__(self, settings: Settings, sessions: sessionmaker,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings, self.sessions = settings, sessions
        auth = None
        if settings.alarm_relay_username and settings.alarm_relay_password:
            auth = httpx.BasicAuth(settings.alarm_relay_username, settings.alarm_relay_password.get_secret_value())
        self._client = httpx.AsyncClient(timeout=settings.alarm_timeout_seconds, auth=auth, transport=transport,
                                         follow_redirects=False)
        self._webhook = httpx.AsyncClient(timeout=settings.alarm_timeout_seconds, transport=transport,
                                          follow_redirects=False)
        self._last_activation: float | None = None
        self._off_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self.last_error: str | None = None

    async def aclose(self) -> None:
        if self._off_task is not None:
            self._off_task.cancel()
        await self._client.aclose()
        await self._webhook.aclose()

    # --- status ---

    def output_status(self) -> dict:
        s = self.settings
        configured = s.alarm_output != "http_relay" or bool(s.alarm_relay_on_url)
        problem = None
        if s.alarm_output == "http_relay":
            for name, url in (("ALARM_RELAY_ON_URL", s.alarm_relay_on_url), ("ALARM_RELAY_OFF_URL", s.alarm_relay_off_url)):
                if url:
                    try:
                        lan_url(url, s)
                    except OutputRefused as exc:
                        problem, configured = f"{name}: {exc}", False
        return {
            "output": s.alarm_output,  # simulation | http_relay | none
            "physical": s.alarm_output == "http_relay",
            "configured": configured,
            "problem": problem,
            "duration_seconds": s.alarm_duration_seconds,
            "cooldown_seconds": s.alarm_cooldown_seconds,
            "max_silence_minutes": s.alarm_max_silence_minutes,
            "webhook": bool(s.alert_webhook_url),
            "last_error": self.last_error,
        }

    # --- driving the output ---

    async def _relay(self, url: str) -> None:
        lan_url(url, self.settings)
        resp = await self._client.request(self.settings.alarm_relay_method, url)
        if resp.status_code >= 400:
            raise OutputRefused(f"the relay answered HTTP {resp.status_code}")

    async def activate(self, ignore_silence: bool = False) -> str:
        s = self.settings
        if s.alarm_output == "none":
            return DISABLED
        with self.sessions() as db:
            silenced = silenced_until(db)
        if silenced and not ignore_silence:
            return SILENCED
        async with self._lock:
            now = time.monotonic()
            if self._last_activation is not None and now - self._last_activation < s.alarm_cooldown_seconds:
                return COOLDOWN
            self._last_activation = now
            if s.alarm_output == "simulation":
                log.warning("ALARM (simulation): the output would now be on for %.0f s", s.alarm_duration_seconds)
                return SIMULATED
            try:
                await self._relay(s.alarm_relay_on_url)
            except (OutputRefused, httpx.HTTPError) as exc:
                self.last_error = f"relay on: {exc if isinstance(exc, OutputRefused) else type(exc).__name__}"
                log.error("Alarm output failed: %s", self.last_error)
                return FAILED
            self.last_error = None
            log.warning("ALARM: relay switched on for %.0f s", s.alarm_duration_seconds)
            if s.alarm_relay_off_url:
                if self._off_task is not None:
                    self._off_task.cancel()
                self._off_task = asyncio.create_task(self._off_later(s.alarm_duration_seconds))
            return ACTIVATED

    async def _off_later(self, delay: float) -> None:
        await asyncio.sleep(delay)
        await self.stop()

    async def stop(self) -> bool:
        """Switch the relay off now (silence, end of duration). True if an off request was sent and accepted."""
        if self.settings.alarm_output != "http_relay" or not self.settings.alarm_relay_off_url:
            return False
        try:
            await self._relay(self.settings.alarm_relay_off_url)
        except (OutputRefused, httpx.HTTPError) as exc:
            self.last_error = f"relay off: {exc if isinstance(exc, OutputRefused) else type(exc).__name__}"
            log.error("Alarm output could not be switched off: %s", self.last_error)
            return False
        log.info("Alarm relay switched off")
        return True

    # --- alerts ---

    async def _deliver(self, alert: Alert) -> str:
        s = self.settings
        if not s.alert_webhook_url:
            return "in-app only"
        if alert.kind == NEEDS_REVIEW and not s.alert_webhook_review:
            return "in-app only (review alerts are not sent)"
        payload = {"alert_id": alert.id, "kind": alert.kind, "camera": alert.camera, "detail": alert.detail,
                   "alarm": alert.alarm, "created_at": as_utc(alert.created_at).isoformat()}
        try:
            resp = await self._webhook.post(lan_url(s.alert_webhook_url, s), json=payload)
        except OutputRefused as exc:
            return f"webhook refused: {exc}"[:500]
        except httpx.HTTPError as exc:
            return f"webhook failed: {type(exc).__name__}"
        return f"webhook HTTP {resp.status_code}"

    async def raise_alert(self, kind: str, camera: str | None, detail: str, crossing_id: str | None = None,
                          alarm: bool = False, ignore_silence: bool = False) -> str:
        state = await self.activate(ignore_silence) if alarm else NONE
        with self.sessions() as db:
            alert = Alert(kind=kind, camera=camera, crossing_id=crossing_id, detail=detail[:500], alarm=state,
                          created_at=utcnow())
            db.add(alert)
            db.commit()
            alert_id = alert.id
        delivery = await self._deliver(alert)
        with self.sessions() as db:
            row = db.get(Alert, alert_id)
            if row is not None:
                row.delivery = delivery
                db.commit()
        log.info("Alert %s (%s, %s): alarm %s, %s", alert_id, kind, camera, state, delivery)
        return alert_id

    async def on_crossing(self, crossing_id: str, line, verdict: str, reason: str | None) -> None:
        if verdict == "UNAUTHORIZED":
            await self.raise_alert(UNAUTHORIZED_ENTRY, line.camera, f"entry not matched to an authorized person ({reason})",
                                   crossing_id, alarm=line.alarm_on_unauthorized)
        elif verdict == "NEEDS_REVIEW":
            await self.raise_alert(NEEDS_REVIEW, line.camera, f"entry needs review ({reason})", crossing_id)

    async def test(self, username: str) -> str:
        """Manual test: drives the configured output once (ignoring silence, not the cooldown)."""
        return await self.raise_alert(ALARM_TEST, None, f"manual alarm test by {username}", alarm=True,
                                      ignore_silence=True)


def silence_until(minutes: int) -> datetime:
    return utcnow() + timedelta(minutes=minutes)
