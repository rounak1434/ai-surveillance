"""Gate crossing logic, gate verdicts, alarm output guards, roles and accounts (0006).

The tracker and verdict tests are pure logic. The route tests use the respx-mocked Frigate from
conftest; no MQTT broker, relay or camera is involved, so none of this shows the behaviour on the
real hardware.
"""

import asyncio

import httpx
import pytest

from ai_surveillance import alarm as alarm_mod
from ai_surveillance.config import Settings
from ai_surveillance.db import AdminUser, Alert, Database, GateCrossing, GateLine
from ai_surveillance.face_detection import DetectedFace
from ai_surveillance.gate import (AUTHORIZED, IN, NEEDS_REVIEW, OUT, UNAUTHORIZED, Crossing, GateTracker, Line,
                                  foot_point, segments_intersect, side_of, snapshot_box, verdict_for)
from ai_surveillance.recognition import INCONCLUSIVE, UNRECOGNIZED, Match
from ai_surveillance.security import hash_password

from .conftest import ADMIN_PASSWORD, ADMIN_USER

# A vertical line in the middle of the frame, from top to bottom; "right" of p1 -> p2 (y down) is x < 0.5.
LINE = Line("l" * 32, "entrance", 0.5, 0.1, 0.5, 0.9, "right", True, False, 10)
BOX = (0.0, 0.0, 1.0, 1.0)


# --- geometry and tracking ------------------------------------------------------------------

def test_sides_follow_image_coordinates():
    assert side_of(LINE, 0.3, 0.5, 0.02) == 1  # right of a downward line is the left half of the image
    assert side_of(LINE, 0.7, 0.5, 0.02) == -1
    assert side_of(LINE, 0.51, 0.5, 0.02) == 0  # dead zone


def test_step_must_cross_the_drawn_segment():
    assert segments_intersect((0.3, 0.5), (0.7, 0.5), LINE)
    assert not segments_intersect((0.3, 0.95), (0.7, 0.95), LINE)  # below the end of the line


def test_foot_point_is_the_bottom_centre_in_frame_fractions():
    assert foot_point([100, 100, 300, 700], 1000, 1000) == (0.2, 0.7)
    assert foot_point([1, 2, 3], 1000, 1000) is None


def test_person_box_is_taken_from_the_frame_that_was_analysed():
    # Frigate 0.18.2: an in-progress event's snapshot is the tracked object's best (thumbnail) frame,
    # whose box is `after.snapshot.box`, not the crossing frame's `after.box`.
    after = {"box": [500, 0, 700, 1000], "frame_time": 20.0,
             "snapshot": {"frame_time": 18.5, "box": [100, 100, 300, 700]}}
    snap = snapshot_box(after, 1000, 1000)
    assert snap == (18.5, (0.1, 0.1, 0.3, 0.7))
    c = Crossing(LINE, "t1", IN, 20.0, (0.6, 1.0), (0.5, 0.0, 0.7, 1.0), snap)
    assert c.box_at(20.0) == (0.5, 0.0, 0.7, 1.0)
    assert c.box_at(18.5) == (0.1, 0.1, 0.3, 0.7)
    assert c.box_at(19.0) is None  # the best frame changed after the message: position unknown
    assert c.box_at(None) is None
    assert snapshot_box({"snapshot": None}, 1000, 1000) is None


def _walk(tracker, xs, track="t1", start=1.0, line=LINE):
    out = []
    for i, x in enumerate(xs):
        c = tracker.update(line, track, start + i, (x, 0.5), BOX)
        if c:
            out.append(c.direction)
    return out


def test_one_crossing_per_directional_crossing():
    tracker = GateTracker(0.02, 600)
    assert _walk(tracker, [0.7, 0.6, 0.52, 0.4, 0.3]) == [IN]  # from the out side (x > 0.5) into the in side


def test_jitter_on_the_line_and_cooldown_do_not_duplicate():
    tracker = GateTracker(0.02, 600)
    # crosses in at t=3, wobbles back and forth within the 10 s cooldown
    assert _walk(tracker, [0.7, 0.6, 0.4, 0.6, 0.4, 0.6]) == [IN]
    tracker = GateTracker(0.02, 600)
    assert _walk(tracker, [0.7, 0.4] + [0.4] * 12 + [0.7]) == [IN, OUT]  # back out after the cooldown


def test_repeated_or_out_of_order_messages_are_ignored():
    tracker = GateTracker(0.02, 600)
    assert tracker.update(LINE, "t", 5.0, (0.7, 0.5), BOX) is None
    assert tracker.update(LINE, "t", 6.0, (0.3, 0.5), BOX).direction == IN
    assert tracker.update(LINE, "t", 6.0, (0.3, 0.5), BOX) is None  # same message again
    assert tracker.update(LINE, "t", 5.5, (0.7, 0.5), BOX) is None  # late message


def test_a_new_track_needs_a_side_first():
    tracker = GateTracker(0.02, 600)
    assert tracker.update(LINE, "t", 1.0, (0.3, 0.5), BOX) is None  # first sight on the in side: no crossing


# --- verdicts ---------------------------------------------------------------------------------

def _face(outcome, similarity=None, w=120, **quality):
    face = DetectedFace(box={"x": 10, "y": 10, "w": w, "h": w}, score=0.9, keypoints5=[], quality=quality, crop_jpeg=None)
    face.match = Match(outcome, None, similarity)
    return face


def test_only_a_clear_non_match_against_a_gallery_is_unauthorized():
    s = Settings(_env_file=None)
    assert verdict_for(_face(UNRECOGNIZED, 0.1), s)[0] == UNAUTHORIZED
    assert verdict_for(_face("AUTHORIZED", 0.8), s)[0] == AUTHORIZED
    assert verdict_for(_face(UNRECOGNIZED, None), s) == (NEEDS_REVIEW, "gallery_empty")
    assert verdict_for(_face(INCONCLUSIVE, 0.4), s)[0] == NEEDS_REVIEW
    assert verdict_for(_face(UNRECOGNIZED, 0.1, w=20), s) == (NEEDS_REVIEW, "face_too_small")
    assert verdict_for(_face(UNRECOGNIZED, 0.1, touches_edge=True), s) == (NEEDS_REVIEW, "face_touches_edge")


# --- alarm output -----------------------------------------------------------------------------

@pytest.mark.parametrize("url", ["http://relay.lan/on", "ftp://192.168.1.5/", "http://127.0.0.1/on",
                                 "http://8.8.8.8/on"])
def test_relay_urls_must_be_lan_ip_addresses(url):
    with pytest.raises(alarm_mod.OutputRefused):
        alarm_mod.lan_url(url, Settings(_env_file=None))


def test_http_relay_needs_an_on_url():
    with pytest.raises(ValueError):
        Settings(alarm_output="http_relay", _env_file=None)


def _service(settings, handler):
    db = Database(settings.database_url)
    db.migrate()
    return alarm_mod.AlarmService(settings, db.sessionmaker, transport=httpx.MockTransport(handler)), db


def test_simulation_never_calls_the_network(settings):
    calls = []
    service, db = _service(settings, lambda r: calls.append(r) or httpx.Response(200))
    assert asyncio.run(service.activate()) == alarm_mod.SIMULATED and calls == []


def test_relay_is_switched_and_cooldown_and_silence_hold_it(settings):
    settings.alarm_output, settings.alarm_relay_on_url = "http_relay", "http://192.168.1.60/relay?on"
    calls = []
    service, db = _service(settings, lambda r: calls.append(str(r.url)) or httpx.Response(200))

    async def run():
        first = await service.activate()
        second = await service.activate()  # inside the cooldown
        return first, second

    assert asyncio.run(run()) == (alarm_mod.ACTIVATED, alarm_mod.COOLDOWN) and calls == [settings.alarm_relay_on_url]
    with db.sessionmaker() as s:
        alarm_mod.set_silence(s, alarm_mod.silence_until(10), "op")
        s.commit()
    service._last_activation = None
    assert asyncio.run(service.activate()) == alarm_mod.SILENCED and len(calls) == 1


def test_needs_review_raises_an_alert_but_never_the_alarm(settings):
    from datetime import UTC, datetime
    calls = []
    service, db = _service(settings, lambda r: calls.append(r) or httpx.Response(200))
    line = Line("l" * 32, "entrance", 0.5, 0.1, 0.5, 0.9, "right", True, True, 10)  # alarm switched on
    crossing_id = "c" * 32
    with db.sessionmaker() as s:
        s.add(GateLine(id=line.id, camera=line.camera, name="test", x1=line.x1, y1=line.y1, x2=line.x2, y2=line.y2,
                       in_side=line.in_side, record_exits=line.record_exits, enabled=True,
                       alarm_on_unauthorized=line.alarm_on_unauthorized, cooldown_seconds=line.cooldown_seconds,
                       updated_by="test"))
        s.flush()
        s.add(GateCrossing(id=crossing_id, line_id=line.id, camera=line.camera, frigate_event_id="f" * 30,
                           sequence=1, direction=IN, crossed_at=datetime.now(UTC), frame_time=1.0,
                           point_x=0.4, point_y=0.5, verdict=NEEDS_REVIEW, reason="several_faces"))
        s.commit()
    asyncio.run(service.on_crossing(crossing_id, line, NEEDS_REVIEW, "several_faces"))
    with db.sessionmaker() as s:
        alert = s.query(Alert).one()
    assert alert.kind == "needs_review" and alert.crossing_id == crossing_id and alert.alarm == alarm_mod.NONE


# --- roles and accounts ---------------------------------------------------------------------

def _add_user(settings, username, role, password="viewer-password-1"):
    db = Database(settings.database_url)
    with db.sessionmaker() as s:
        s.add(AdminUser(username=username, role=role, password_hash=hash_password(password)))
        s.commit()
    db.engine.dispose()


def _login(client, username, password):
    assert client.post("/api/auth/login", json={"username": username, "password": password}).status_code == 200


def test_viewer_sees_crossings_but_no_faces_footage_or_configuration(client, settings):
    _add_user(settings, "watch", "viewer")
    _login(client, "watch", "viewer-password-1")
    assert client.get("/api/auth/me").json() == {"username": "watch", "role": "viewer"}
    assert client.get("/api/gate/crossings").status_code == 200
    assert client.get("/api/alerts").status_code == 200
    for method, path in [("get", "/api/face-events"), ("get", "/api/people"), ("get", "/api/captures"),
                         ("post", "/api/footage/face-events/" + "a" * 32), ("post", "/api/alarm/silence"),
                         ("get", "/api/users"), ("get", "/api/devices"), ("get", "/api/audit-log"),
                         ("get", "/api/privacy")]:
        assert client.request(method.upper(), path, json={"minutes": 5}).status_code == 403, path


def test_operator_can_silence_but_not_configure(client, settings):
    _add_user(settings, "desk", "operator", "operator-password-1")
    _login(client, "desk", "operator-password-1")
    assert client.post("/api/alarm/silence", json={"minutes": 5}).json()["silenced_until"]
    assert client.request("DELETE", "/api/alarm/silence").json()["silenced_until"] is None
    assert client.post("/api/alarm/test", json={"password": "operator-password-1"}).status_code == 403
    assert client.put("/api/gate/lines/entrance", json={}).status_code in (403, 422)


def test_last_administrator_cannot_be_demoted_or_removed(signed_in):
    me = next(u for u in signed_in.get("/api/users").json()["items"] if u["username"] == ADMIN_USER)
    resp = signed_in.patch(f"/api/users/{me['id']}", json={"role": "viewer", "password": ADMIN_PASSWORD})
    assert resp.status_code == 409
    created = signed_in.post("/api/users", json={"username": "second", "role": "admin",
                                                 "new_password": "second-admin-pass", "password": ADMIN_PASSWORD})
    assert created.status_code == 201
    assert signed_in.request("DELETE", f"/api/users/{me['id']}", json={"password": ADMIN_PASSWORD}).status_code == 409


def test_password_change_needs_the_current_password_and_keeps_this_session(signed_in):
    bad = signed_in.post("/api/auth/password", json={"current_password": "wrong-password-123",
                                                     "new_password": "a-brand-new-password"})
    assert bad.status_code == 403
    ok = signed_in.post("/api/auth/password", json={"current_password": ADMIN_PASSWORD,
                                                    "new_password": "a-brand-new-password"})
    assert ok.status_code == 204 and signed_in.get("/api/auth/me").status_code == 200


def test_disabled_accounts_cannot_sign_in(client, settings):
    _add_user(settings, "gone", "operator", "operator-password-1")
    db = Database(settings.database_url)
    with db.sessionmaker() as s:
        s.query(AdminUser).filter_by(username="gone").one().disabled = True
        s.commit()
    db.engine.dispose()
    resp = client.post("/api/auth/login", json={"username": "gone", "password": "operator-password-1"})
    assert resp.status_code == 401


def test_footage_older_than_frigates_retention_is_reported_as_expired(signed_in, settings):
    from datetime import UTC, datetime, timedelta

    from ai_surveillance.db import FaceEvent

    db = Database(settings.database_url)
    old = datetime.now(UTC) - timedelta(days=settings.frigate_recording_days + 1)
    with db.sessionmaker() as s:
        event = FaceEvent(frigate_event_id="1.0-old", camera="entrance", started_at=old, ended_at=old,
                          status="no_faces_detected")
        s.add(event)
        s.commit()
        event_id = event.id
    db.engine.dispose()
    resp = signed_in.post(f"/api/footage/face-events/{event_id}")
    assert resp.status_code == 410 and resp.json()["error"] == "footage_expired"
