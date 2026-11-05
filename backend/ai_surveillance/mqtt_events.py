"""Real-time Frigate events over MQTT.

Frigate publishes every tracked object's lifecycle on `<prefix>/events` as JSON
{"type": "new" | "update" | "end", "before": {...}, "after": {...}}; `after` carries the stable
event id (the track id), camera, label, frame_time and box. This module subscribes (QoS 1) and
- hands each person message to the gate service (gate.py), which counts line crossings;
- wakes the face-event ingestion shortly after a person event ends, so face events (and the gate
  crossing's link to them) appear within seconds instead of at the next poll.

Reliability: ids come from Frigate, not from the messages' order. A message delivered twice or
late changes nothing (gate: frame times must increase; face events: one row per Frigate event id).
The HTTP poll keeps running as a reconciliation pass (FACE_RECONCILE_SECONDS while connected,
FACE_POLL_SECONDS while not), so events published while the api or the broker was down are still
ingested. The connection is retried with exponential backoff up to MQTT_RECONNECT_MAX_SECONDS.
Crossings that happen while MQTT is down are not counted (there are no positions to compare).
"""

import asyncio
import json
import logging
from dataclasses import dataclass

from .config import Settings
from .db import utcnow

log = logging.getLogger(__name__)

_END_DELAY_SECONDS = 2.0  # Frigate writes the finished event to its database right after publishing "end"


@dataclass
class MqttStatus:
    enabled: bool = True
    connected: bool = False
    last_message_at: str | None = None
    last_error: str | None = None
    reconnects: int = 0
    messages: int = 0

    def as_dict(self) -> dict:
        return {"enabled": self.enabled, "connected": self.connected, "last_message_at": self.last_message_at,
                "last_error": self.last_error, "reconnects": self.reconnects, "messages": self.messages}


async def handle_message(raw: bytes, gate, wake: asyncio.Event | None) -> None:
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return
    if not isinstance(payload, dict):
        return
    if gate is not None:
        try:
            await gate.on_event(payload)
        except Exception:
            log.exception("Gate processing of an MQTT event failed")
    after = payload.get("after")
    if (wake is not None and payload.get("type") == "end" and isinstance(after, dict)
            and after.get("label") == "person"):
        asyncio.get_running_loop().call_later(_END_DELAY_SECONDS, wake.set)


async def mqtt_loop(settings: Settings, status: MqttStatus, gate, wake: asyncio.Event | None) -> None:
    import aiomqtt  # only needed when MQTT is enabled

    topic = f"{settings.mqtt_topic_prefix.rstrip('/')}/events"
    password = settings.mqtt_password.get_secret_value() if settings.mqtt_password else None
    delay = 1.0
    while True:
        try:
            async with aiomqtt.Client(settings.mqtt_host, settings.mqtt_port, username=settings.mqtt_username or None,
                                      password=password, identifier="ai-surveillance-api") as client:
                await client.subscribe(topic, qos=1)
                status.connected, status.last_error, delay = True, None, 1.0
                log.info("MQTT: connected to %s:%d, subscribed to %s", settings.mqtt_host, settings.mqtt_port, topic)
                async for message in client.messages:
                    status.messages += 1
                    status.last_message_at = utcnow().isoformat()
                    await handle_message(bytes(message.payload), gate, wake)
        except asyncio.CancelledError:
            status.connected = False
            raise
        except Exception as exc:  # aiomqtt.MqttError, OSError: broker down, refused, connection lost
            was_connected = status.connected
            status.connected, status.last_error = False, f"{type(exc).__name__}: {exc}"[:300]
            status.reconnects += 1
            if was_connected or status.reconnects == 1:
                log.warning("MQTT: %s; retrying (event updates paused, HTTP polling continues)", status.last_error)
        await asyncio.sleep(delay)
        delay = min(delay * 2, settings.mqtt_reconnect_max_seconds)
