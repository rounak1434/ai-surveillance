# Gate lines, crossings and real-time events

## What it does
An administrator draws a line on a camera's still frame (Gate page) and picks the side that counts as **in**. Every person Frigate tracks is followed across frames. One **crossing** is stored each time the person moves from one side of the line to the other. Entries are checked against the authorized people straight away. Exits are recorded too, if the line is set to, but they are not checked.

## How tracking works (`gate.py`, `mqtt_events.py`)
- **Tracks and positions.** Frigate's tracker gives each person a stable id (its event id). On MQTT topic `frigate/events`, Frigate publishes `new`, `update` and `end` messages for that track, each with the person's `box` in detect-stream pixels and the `frame_time`. The api subscribes with QoS 1.
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
1. The api takes the track's current best frame from Frigate (`/api/events/<id>/snapshot.jpg`, or the recording frame) and runs the same detector and matcher as for face events.
2. Only a face whose centre lies inside the person's box counts.

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

## Not verified (needs the real stack)
- **Message frequency.** How often Frigate 0.18.2 publishes `update` messages for a walking person on this camera is not known. If updates are sparse, a fast walker can be first seen beyond the line's end, and then no crossing is counted. Measure this with real walks (acceptance checklist).
- **In-progress snapshots.** That `/api/events/<id>/snapshot.jpg` serves a snapshot for an event that is still in progress is expected from Frigate's source, but has not been observed.
- **Payload shape.** The MQTT payload shape (`after.box`, `after.frame_time`) comes from Frigate's documentation. It has not been checked against the v0.18.2 source in this repository's FRIGATE-API.md audit.
