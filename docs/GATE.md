# Gate lines, crossings and real-time events

## What it does
An administrator draws a line on a camera's still frame (Gate page) and picks the side that counts as **in**. Every person Frigate tracks is followed across frames. One **crossing** is stored each time the person moves from one side of the line to the other. Entries are checked against the authorized people straight away. Exits are recorded too, if the line is set to, but they are not checked.

## How tracking works (`gate.py`, `mqtt_events.py`)
- **Tracks and positions.** Frigate's tracker gives each person a stable id (its event id). On MQTT topic `frigate/events`, Frigate publishes `new`, `update` and `end` messages for that track. Each one carries the person's `box` in detect-stream pixels, the `frame_time`, and the box and time of the best frame so far (`snapshot`). Frigate publishes at its `mqtt.qos`, which defaults to 0. The api's QoS 1 subscription therefore still delivers each message at most once.
- **How often.** Frigate 0.18.2 sends an `update` when the person's bottom centre has moved about 5–6 % of the frame, or when zones or the stationary state change. It also sends one at least every 5 s while the best frame improves (1 s for a person large enough for face recognition). Messages are not sent per frame. Draw the line so that it extends beyond the walkway on both ends by more than one such step; otherwise a person who changes side beyond the end of the line is not counted.
- **The person's position** is the bottom centre of the box (where the feet are), as a fraction of the frame. The line is stored as fractions too, so it fits every stream resolution.
- **A crossing** counts only when both of these hold:
  - the position changes sides;
  - the step between the two positions intersects the drawn segment. Walking around the end of the line does not count.
- **Dead zone.** Positions closer to the line than `GATE_DEAD_ZONE` (default 2 % of the frame) keep the previous side. A person standing on the line therefore produces no crossings.
- **Duplicate protection:**
  - a message whose frame time is not newer than the track's last one is ignored, so repeated or late MQTT deliveries change nothing;
  - after a crossing, the same track's further crossings of that line are ignored for the line's **cooldown** (seconds, default 10);
  - crossings are unique per line, track and sequence number in the database;
  - after a restart, a track must be seen on one side before it can cross.

## The check of an entry
While recognition is switched on, an entry is checked as follows:
1. The api takes the track's current best frame from Frigate (`/api/events/<id>/snapshot.jpg`, or the recording frame at the same time) and runs the same detector and matcher as for face events. While the person is still tracked, Frigate serves the best frame so far, which is usually not the crossing frame.
2. Only a face whose centre lies inside the person's box **in that frame** counts. The box is the crossing message's `box` when the frame is the crossing frame, or its `snapshot.box` when it is the best frame. If Frigate's best frame changed after the message, the box is unknown and the crossing is `NEEDS_REVIEW` (`person_box_unknown`).

| Verdict | When |
|---|---|
| `AUTHORIZED` | The face matched an active authorized person (an automated match, not a verified identity) |
| `UNAUTHORIZED` | Exactly one clear face, with no quality warning, below the reject threshold against a non-empty gallery |
| `NEEDS_REVIEW` | Any of these: no face, several faces, face too small or cut off at the edge, similarity between the thresholds, several people alike, empty gallery, recognition unavailable, or the check failed |
| `NOT_CHECKED` | Recognition is off, or the crossing is an exit |

Uncertain or poor-quality results are never treated as unauthorized. Attribute estimates are never read.

When Frigate's face event for the same track is stored later, the crossing is linked to it. The crossing then gets that face event's frame, crops and footage.

## Real-time events
- **With MQTT**, a finished person event wakes the face-event ingestion about 2 s later, so face events appear within seconds.
- **The HTTP poll keeps running** as a reconciliation pass: every `FACE_RECONCILE_SECONDS` (60) while MQTT is connected, and every `FACE_POLL_SECONDS` (10) while it is not. Events published while the api or the broker was down are therefore still ingested once.
- **Reconnection** uses exponential backoff, up to `MQTT_RECONNECT_MAX_SECONDS`. The top bar shows "Events live" or "Events delayed".
- **Crossings during an MQTT outage are not counted**, because there are no positions to compare. The Gate page says so while disconnected.

## Setup
- **Compose** runs `mosquitto` on the internal network. It has no published port and is anonymous on that network. `MQTT_ENABLED=true` is the compose default.
- **Frigate's** `mqtt` section (`deploy/frigate/config.yml`) points at `mosquitto`.
- **An existing install** keeps its live Frigate config in `deploy/storage/frigate-config/config.yml`, and that file was seeded once with MQTT off. Use one of these:
  - click **Apply to Frigate** once, which renders from the template; or
  - set `mqtt.enabled: true` and `host: mosquitto` in that file and restart Frigate.
- **On the Gate page**, as an administrator:
  1. Click "Draw line" and then two points on the frame.
  2. Choose the in side, the cooldown and whether exits are recorded.
  3. Optionally switch on "Alarm on unauthorized entry".
  4. Save; this needs your password.

## Verified from source, not yet observed (needs the real stack)
The topic, payload fields, update rule, in-progress snapshot and export behaviour were checked against the Frigate v0.18.2 source on 2026-11-05 (FRIGATE-API.md, "MQTT and in-progress events"). Nothing has been observed on a running Frigate, camera or Ubuntu host. ACCEPTANCE-CHECKLIST.md section 2a covers that. Still unknown until then:
- **The real update rate** on this camera with real walking speeds, and so how often crossings are missed.
- **How often `person_box_unknown` occurs**, which depends on how often Frigate's best frame changes between a message and the check.
- **Messages lost** during a broker or network hiccup, since delivery is QoS 0.
- **Recognition accuracy** on in-progress best frames.
