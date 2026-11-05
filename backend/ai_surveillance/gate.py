"""Virtual gate lines: directional crossings of Frigate-tracked people, checked against the gallery.

Tracking: Frigate tracks each person across frames and gives the track a stable id (its event id).
Over MQTT it publishes the track's box with every event update (mqtt_events.py). The person's
position is the bottom centre of that box (the feet), as a fraction of the detect frame, so it
can be compared with a line drawn on any stream of the camera.

Crossing: the line runs p1 -> p2; its "in" side is to the left or right of that direction (image
coordinates, y down). A track crosses when its position moves from one side to the other and the
step between the two positions intersects the drawn segment (passing beyond the line's end does
not count). Positions closer to the line than GATE_DEAD_ZONE keep the previous side, so a person
standing on the line does not produce crossings.

Duplicate protection:
- an update whose frame time is not newer than the track's last one is ignored (MQTT may deliver a
  message twice, and messages may arrive out of order);
- after a crossing, the same track's further crossings of that line are ignored for the line's
  cooldown (seconds of frame time);
- crossings are unique per (line, track, sequence) in the database;
- after a restart a track needs a fresh side before it can cross, so nothing is counted twice.

Check: each entry ("in") is checked at once: the track's current best frame (Frigate's event
snapshot, or the recording frame) goes through the same face detection and recognition as face
events, and only the face inside the person's box counts. While the event is in progress that
best frame is the tracked object's thumbnail frame, usually not the crossing frame (Frigate
0.18.2 `event_snapshot`, `TrackedObject.get_img_bytes`), so the person's box is taken from the
frame that was actually analysed: the crossing message's `box` or its `snapshot.box`, matched by
frame time. A frame matching neither needs review. Verdicts:
  AUTHORIZED     the face matched an active authorized person
  UNAUTHORIZED   one clear face (no quality warning) that is below the reject threshold against a
                 non-empty gallery
  NEEDS_REVIEW   everything uncertain: no face, several faces, poor quality, inconclusive
                 similarity, empty gallery, recognition unavailable or failed
  NOT_CHECKED    recognition is switched off, or the crossing is an exit
Uncertain or poor-quality faces are never treated as unauthorized. Facial attribute estimates
are never read here. When Frigate's face event for the same track is stored later, the crossing
is linked to it (frame, crops, footage).
"""

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from . import recognition
from .config import Settings
from .db import GateCrossing, GateLine, utcnow
from .face_detection import FACES_DETECTED, detect_event_faces
from .frigate_client import FrigateError, PersonEvent
from .inference_client import InferenceUnavailable

log = logging.getLogger(__name__)

AUTHORIZED = "AUTHORIZED"
UNAUTHORIZED = "UNAUTHORIZED"
NEEDS_REVIEW = "NEEDS_REVIEW"
NOT_CHECKED = "NOT_CHECKED"
PENDING = "pending"
VERDICTS = frozenset({PENDING, AUTHORIZED, UNAUTHORIZED, NEEDS_REVIEW, NOT_CHECKED})

IN, OUT = "in", "out"
_CHECK_CONCURRENCY = 2
_FACE_IN_BOX_MARGIN = 0.1  # a face centre may lie this fraction of the box size outside the person box
_FRAME_TIME_TOLERANCE = 0.001  # seconds; frames are at least 1/30 s apart


# --- geometry -------------------------------------------------------------------------------

@dataclass(frozen=True)
class Line:
    id: str
    camera: str
    x1: float
    y1: float
    x2: float
    y2: float
    in_side: str  # "left" | "right"
    record_exits: bool
    alarm_on_unauthorized: bool
    cooldown_seconds: int

    @classmethod
    def from_row(cls, row: GateLine) -> "Line":
        return cls(row.id, row.camera, row.x1, row.y1, row.x2, row.y2, row.in_side, row.record_exits,
                   row.alarm_on_unauthorized, row.cooldown_seconds)


def signed_distance(line: Line, x: float, y: float) -> float:
    """> 0 on the right of p1 -> p2 (image coordinates, y down), < 0 on the left; in frame fractions."""
    dx, dy = line.x2 - line.x1, line.y2 - line.y1
    length = math.hypot(dx, dy)
    if length == 0:
        return 0.0
    return (dx * (y - line.y1) - dy * (x - line.x1)) / length


def _orient(ax, ay, bx, by, cx, cy) -> float:
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def segments_intersect(p: tuple[float, float], q: tuple[float, float], line: Line) -> bool:
    """Whether the step p -> q intersects the line segment (touching counts)."""
    a, b = (line.x1, line.y1), (line.x2, line.y2)
    d1, d2 = _orient(*a, *b, *p), _orient(*a, *b, *q)  # p and q on opposite sides of the line
    d3, d4 = _orient(*p, *q, *a), _orient(*p, *q, *b)  # a and b on opposite sides of the step
    return min(d1, d2) <= 0 <= max(d1, d2) and min(d3, d4) <= 0 <= max(d3, d4)


def side_of(line: Line, x: float, y: float, dead_zone: float) -> int:
    """+1 in side, -1 out side, 0 inside the dead zone."""
    distance = signed_distance(line, x, y)
    if abs(distance) <= dead_zone:
        return 0
    right = distance > 0
    return 1 if right == (line.in_side == "right") else -1


def foot_point(box, width: float, height: float) -> tuple[float, float] | None:
    """Bottom centre of a Frigate box [x_min, y_min, x_max, y_max] (detect pixels), as frame fractions."""
    if not (isinstance(box, list | tuple) and len(box) == 4 and all(isinstance(v, int | float) for v in box)):
        return None
    if width <= 0 or height <= 0:
        return None
    x0, _y0, x1, y1 = box
    return min(max((x0 + x1) / 2 / width, 0.0), 1.0), min(max(y1 / height, 0.0), 1.0)


def snapshot_box(after: dict, width: float, height: float) -> tuple[float, tuple[float, float, float, float]] | None:
    """(frame time, normalised box) of the track's best frame so far: Frigate's `after.snapshot`
    (the tracked object's thumbnail data), or None while it has none."""
    snapshot = after.get("snapshot")
    if not isinstance(snapshot, dict):
        return None
    frame_time, box = snapshot.get("frame_time"), snapshot.get("box")
    if not isinstance(frame_time, int | float) or foot_point(box, width, height) is None:
        return None
    return float(frame_time), (box[0] / width, box[1] / height, box[2] / width, box[3] / height)


# --- tracking -------------------------------------------------------------------------------

@dataclass
class TrackState:
    side: int = 0  # last side outside the dead zone
    point: tuple[float, float] | None = None  # position where that side was last seen
    frame_time: float = 0.0
    last_crossing_time: float | None = None
    seen: float = field(default_factory=time.monotonic)


@dataclass(frozen=True)
class Crossing:
    line: Line
    track_id: str
    direction: str
    frame_time: float
    point: tuple[float, float]
    person_box: tuple[float, float, float, float]  # normalised x0, y0, x1, y1, at frame_time
    snapshot: tuple[float, tuple[float, float, float, float]] | None = None  # best frame's (time, box)

    def box_at(self, frame_time: float | None) -> tuple[float, float, float, float] | None:
        """The person's box in the frame taken at `frame_time`, if this crossing knows it."""
        if frame_time is None:
            return None
        if abs(frame_time - self.frame_time) <= _FRAME_TIME_TOLERANCE:
            return self.person_box
        if self.snapshot is not None and abs(frame_time - self.snapshot[0]) <= _FRAME_TIME_TOLERANCE:
            return self.snapshot[1]
        return None


class GateTracker:
    """Pure crossing logic (no I/O): feed it positions, it returns crossings."""

    def __init__(self, dead_zone: float, track_timeout: float) -> None:
        self.dead_zone, self.track_timeout = dead_zone, track_timeout
        self.tracks: dict[tuple[str, str], TrackState] = {}  # (line id, track id)

    def update(self, line: Line, track_id: str, frame_time: float, point: tuple[float, float],
               person_box: tuple[float, float, float, float]) -> Crossing | None:
        key = (line.id, track_id)
        state = self.tracks.get(key)
        if state is None:
            state = self.tracks[key] = TrackState()
        elif frame_time <= state.frame_time:
            return None  # duplicate or out-of-order message
        state.frame_time, state.seen = frame_time, time.monotonic()
        side = side_of(line, *point, self.dead_zone)
        if side == 0:
            return None
        previous, previous_point = state.side, state.point
        state.side, state.point = side, point
        if previous == 0 or previous == side or previous_point is None:
            return None
        if not segments_intersect(previous_point, point, line):
            return None  # changed side beyond the end of the drawn segment
        if state.last_crossing_time is not None and frame_time - state.last_crossing_time < line.cooldown_seconds:
            return None
        state.last_crossing_time = frame_time
        return Crossing(line, track_id, IN if side == 1 else OUT, frame_time, point, person_box)

    def end(self, track_id: str) -> None:
        for key in [k for k in self.tracks if k[1] == track_id]:
            del self.tracks[key]

    def expire(self) -> None:
        cutoff = time.monotonic() - self.track_timeout
        for key in [k for k, s in self.tracks.items() if s.seen < cutoff]:
            del self.tracks[key]

    def forget_line(self, line_id: str) -> None:
        for key in [k for k in self.tracks if k[0] == line_id]:
            del self.tracks[key]


# --- verdicts -------------------------------------------------------------------------------

def _face_in_person(face, frame_w: int | None, frame_h: int | None, person_box) -> bool:
    if not frame_w or not frame_h:
        return True  # no frame size: cannot tell; the caller still requires exactly one face
    cx = (face.box["x"] + face.box["w"] / 2) / frame_w
    cy = (face.box["y"] + face.box["h"] / 2) / frame_h
    x0, y0, x1, y1 = person_box
    mx, my = (x1 - x0) * _FACE_IN_BOX_MARGIN, (y1 - y0) * _FACE_IN_BOX_MARGIN
    return x0 - mx <= cx <= x1 + mx and y0 - my <= cy <= y1 + my


def poor_quality(face, settings: Settings) -> str | None:
    quality = face.quality or {}
    if quality.get("touches_edge"):
        return "face_touches_edge"
    if quality.get("small_face") or min(face.box["w"], face.box["h"]) < settings.recognition_min_face_px:
        return "face_too_small"
    return None


def verdict_for(face, settings: Settings) -> tuple[str, str]:
    """(verdict, reason) for the one face of a checked entry. Only a clear, good-quality non-match
    against a non-empty gallery is UNAUTHORIZED; anything uncertain needs review."""
    match = face.match
    if match is None:
        return NEEDS_REVIEW, recognition.REASON_UNAVAILABLE
    if match.outcome == recognition.AUTHORIZED:
        return AUTHORIZED, recognition.REASON_MATCH
    quality = poor_quality(face, settings)
    if quality:
        return NEEDS_REVIEW, quality
    if match.outcome == recognition.UNRECOGNIZED and match.similarity is not None:
        return UNAUTHORIZED, recognition.REASON_BELOW_REJECT
    return NEEDS_REVIEW, recognition.outcome_reason(match.outcome, match.similarity,
                                                    settings.recognition_accept_threshold, recognition.STATE_DONE)


# --- service --------------------------------------------------------------------------------

class GateService:
    """Feeds MQTT event updates to the tracker, stores crossings, checks entries, raises alerts."""

    def __init__(self, settings: Settings, sessions: sessionmaker, state) -> None:
        self.settings, self.sessions, self.state = settings, sessions, state
        self.tracker = GateTracker(settings.gate_dead_zone, settings.gate_track_timeout_seconds)
        self.lines: dict[str, Line] = {}  # camera -> enabled line
        self._checks = asyncio.Semaphore(_CHECK_CONCURRENCY)
        self._warned: set[str] = set()
        self.reload()

    def reload(self) -> None:
        """Re-read the lines (after a change through the API). Tracks of changed lines start over."""
        with self.sessions() as db:
            rows = list(db.scalars(select(GateLine).where(GateLine.enabled.is_(True))))
        new = {row.camera: Line.from_row(row) for row in rows}
        for camera, old in self.lines.items():
            if new.get(camera) != old:
                self.tracker.forget_line(old.id)
        self.lines = new

    async def on_event(self, payload: dict) -> Crossing | None:
        """One Frigate `events` message (type new / update / end)."""
        after = payload.get("after")
        if not isinstance(after, dict) or after.get("label") != "person":
            return None
        track_id, camera = after.get("id"), after.get("camera")
        if not isinstance(track_id, str) or not isinstance(camera, str):
            return None
        crossing = None
        line = self.lines.get(camera)
        frame_time = after.get("frame_time")
        if line is not None and isinstance(frame_time, int | float):
            size = await self._detect_size(camera)
            box = after.get("box")
            point = foot_point(box, *size) if size else None
            if point is not None:
                person_box = (box[0] / size[0], box[1] / size[1], box[2] / size[0], box[3] / size[1])
                crossing = self.tracker.update(line, track_id, float(frame_time), point, person_box)
                if crossing is not None:
                    crossing = replace(crossing, snapshot=snapshot_box(after, *size))
        if payload.get("type") == "end":
            self.tracker.end(track_id)
        self.tracker.expire()
        if crossing is not None:
            if crossing.direction == OUT and not line.record_exits:
                return None
            crossing_id = self._store(crossing)
            if crossing_id is not None:
                self.state.spawn(self.check(crossing_id, crossing))
        return crossing

    async def _detect_size(self, camera: str) -> tuple[float, float] | None:
        try:
            config = (await self.state.cameras()).get(camera) or {}
        except FrigateError:
            return None
        detect = config.get("detect") or {}
        width, height = detect.get("width"), detect.get("height")
        if isinstance(width, int | float) and isinstance(height, int | float) and width > 0 and height > 0:
            return float(width), float(height)
        if camera not in self._warned:
            self._warned.add(camera)
            log.warning("Gate line on %s: Frigate reports no detect size; crossings cannot be computed", camera)
        return None

    def _store(self, c: Crossing) -> str | None:
        try:
            with self.sessions() as db:
                if db.get(GateLine, c.line.id) is None:
                    return None  # deleted meanwhile
                sequence = (db.scalar(select(func.max(GateCrossing.sequence)).where(
                    GateCrossing.line_id == c.line.id, GateCrossing.frigate_event_id == c.track_id)) or 0) + 1
                row = GateCrossing(line_id=c.line.id, camera=c.line.camera, frigate_event_id=c.track_id,
                                   sequence=sequence, direction=c.direction,
                                   crossed_at=datetime.fromtimestamp(c.frame_time, UTC), frame_time=c.frame_time,
                                   point_x=c.point[0], point_y=c.point[1],
                                   verdict=PENDING if c.direction == IN else NOT_CHECKED,
                                   reason=None if c.direction == IN else "exit")
                db.add(row)
                db.commit()
                log.info("Gate %s: track %s crossed %s", c.line.camera, c.track_id, c.direction)
                return row.id if c.direction == IN else None
        except IntegrityError:
            return None  # the same crossing was stored meanwhile
        except SQLAlchemyError as exc:
            log.warning("Gate crossing on %s could not be stored: %s", c.line.camera, type(exc).__name__)
            return None

    async def check(self, crossing_id: str, c: Crossing) -> None:
        async with self._checks:
            try:
                verdict, reason, face = await self._evaluate(c)
            except Exception:
                log.exception("Gate check of crossing %s failed", crossing_id)
                verdict, reason, face = NEEDS_REVIEW, "check_failed", None
        match = face.match if face is not None else None
        with self.sessions() as db:
            row = db.get(GateCrossing, crossing_id)
            if row is None:
                return
            row.verdict, row.reason, row.checked_at = verdict, reason, utcnow()
            if match is not None:
                row.outcome, row.similarity, row.person_id = match.outcome, match.similarity, match.person_id
            db.commit()
        if self.state.alarm is not None:
            await self.state.alarm.on_crossing(crossing_id, c.line, verdict, reason)

    async def _evaluate(self, c: Crossing):
        ingestor = self.state.ingestor
        with self.sessions() as db:
            enabled = recognition.is_enabled(db)
        if not enabled:
            return NOT_CHECKED, recognition.REASON_OFF, None
        if ingestor is None:
            return NEEDS_REVIEW, recognition.REASON_UNAVAILABLE, None
        embedder = await ingestor._prepare_recognition()
        enabled, gallery = ingestor._switch_and_gallery(embedder)
        if not enabled:
            return NOT_CHECKED, recognition.REASON_OFF, None
        if gallery is None:
            return NEEDS_REVIEW, recognition.REASON_UNAVAILABLE, None
        event = PersonEvent(c.track_id, c.line.camera, c.frame_time, c.frame_time)
        try:
            result = await detect_event_faces(event, self.state.frigate, self.state.inference, self.settings, True)
        except (FrigateError, InferenceUnavailable) as exc:
            log.info("Gate check on %s: %s", c.line.camera, exc)
            return NEEDS_REVIEW, "check_failed", None
        if result.status != FACES_DETECTED:
            return NEEDS_REVIEW, "no_face", None
        ingestor._match(result, True, gallery)
        if result.recognition_state != recognition.STATE_DONE:
            return NEEDS_REVIEW, recognition.REASON_UNAVAILABLE, None
        person_box = c.box_at(result.frame_time)
        if person_box is None:
            # The analysed frame is neither the crossing frame nor the best frame the crossing
            # message named (the best frame changed meanwhile): where the person is in it is unknown.
            return NEEDS_REVIEW, "person_box_unknown", None
        faces = [f for f in result.faces if _face_in_person(f, result.frame_width, result.frame_height, person_box)]
        if not faces:
            return NEEDS_REVIEW, "no_face_on_person", None
        if len(faces) > 1:
            return NEEDS_REVIEW, "several_faces", None
        verdict, reason = verdict_for(faces[0], self.settings)
        return verdict, reason, faces[0]
