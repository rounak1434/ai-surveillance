# Manual acceptance checklist (gate monitoring features)

Run this on the Ubuntu host with the real stack. Start with the synthetic test stream. Then move to the CP Plus camera, and only with people who have consented. Record each result, with date and commit, in VERIFICATION.md. Nothing here has been performed yet.

## 0. Stack
- [ ] `docker compose ps`: frigate, mosquitto, api, inference and web are running. mosquitto, api and web are healthy.
- [ ] The top bar shows "Events live". `docker compose logs api | grep MQTT` shows "connected … subscribed to frigate/events".
- [ ] Reboot the PC, then cut and restore power once: the stack comes back without manual steps, and the BIOS is set to power on after AC loss.
- [ ] The desktop shortcut opens the console. After importing Caddy's root certificate, there is no certificate warning.

## 1. Accounts and roles
- [ ] Create an operator and a viewer on the *Accounts* page; each creation asks for your password.
- [ ] Viewer: sees Live, Gate and Alerts only. Opening `/api/face-events`, `/api/people` or `/api/captures` directly returns 403. Crossings show no names, and there is no Footage button.
- [ ] Operator: sees face events, frames and footage, and can silence the alarm. Saving a gate line, testing the alarm and the Accounts page are refused.
- [ ] Change your own password: a wrong current password is refused, and your other browser session is signed out.
- [ ] Demoting or disabling the last administrator is refused.
- [ ] `docker compose exec api ai-surveillance create-admin <name>` recovers access, and the audit log shows a `cli` entry.
- [ ] The audit log has entries for profile views, reference-image views, event-image views and footage plays.

## 2. Gate line
- [ ] Draw a line across the walkway, choose the in side and save it: the arrow points into the site.
- [ ] Walk in once: exactly **one** crossing, direction in.
- [ ] Walk out once: one crossing, direction out (if exits are recorded).
- [ ] Stand on the line and sway for 20 s: no extra crossings.
- [ ] Walk in, step back and walk in again within the cooldown: one crossing.
- [ ] Walk in fast and at a slow pace, 10 times each. Count missed crossings, which show how often Frigate publishes positions. Record the result.
- [ ] Two people cross together: one crossing each. If their faces cannot be told apart, both are `NEEDS_REVIEW`.
- [ ] Stop mosquitto (`docker compose stop mosquitto`): the Gate page warns, and face events still arrive by polling. Start it again, and the top bar returns to "Events live".

## 2a. Frigate contract on the running stack
The contract below was checked against the Frigate v0.18.2 source (FRIGATE-API.md, "MQTT and in-progress events"). These steps confirm it on the running instance. Run them from `deploy/` while one consenting person walks through the gate line.

1. **Payload.** Run:
   ```
   docker compose exec mosquitto mosquitto_sub -t 'frigate/events' -v -C 20
   ```
   - [ ] Each message has `type` set to `new`, `update` or `end`, plus `before` and `after`.
   - [ ] `after` has `id`, `camera`, `label: "person"`, `frame_time`, `box` (4 numbers, within the detect width and height) and `snapshot` (`frame_time` and `box`, or `null` early on).
   - [ ] One track has a single `new`, several `update`s and one `end`, all with the same `id`.
2. **Update rate.** Read the `after.frame_time` values of one walk.
   - [ ] Expect a message about every 5–6 % of frame movement, and at least every 5 s while the best frame improves.
   - [ ] Record the largest gap between messages near the line. Draw the line so that it extends at least that far beyond the walkway on both ends.
3. **In-progress snapshot.** While the person is still in view, run:
   ```
   docker compose exec api python -c "import httpx; e=httpx.get('http://frigate:5000/api/events', params={'in_progress':1,'labels':'person','limit':1}).json(); print(e and e[0]['id'])"
   ```
   Then, replacing `<id>` with that id:
   ```
   docker compose exec api python -c "import httpx; r=httpx.get('http://frigate:5000/api/events/<id>/snapshot.jpg', params={'bbox':0,'timestamp':0,'crop':0}); print(r.status_code, r.headers.get('content-type'), r.headers.get('x-frame-time'))"
   ```
   - [ ] The answer is `200 image/jpeg <time>`.
   - [ ] That time equals `after.snapshot.frame_time` of the latest MQTT message for the track, not necessarily its `frame_time`.
4. **Entry check.** Walk in.
   - [ ] The crossing's verdict is never `person_box_unknown` on more than an occasional walk. Record how often it is. Frequent occurrences mean the best frame changes between the message and the check.
5. **Link to the face event.** About 2 s after the person leaves:
   - [ ] the face event with the same Frigate id appears;
   - [ ] the crossing shows its frame, crops and Footage button.
6. **Recording frame and export.** With `FACE_FRAME_SOURCE=recording`:
   - [ ] the face event shows the frame source `recording`;
   - [ ] the crossing's footage export covers the crossing time. The export waits `CLIP_SETTLE_SECONDS` after the end of the range, so recent segments are written first.

## 3. Verdicts and alarm (simulation first)
- [ ] Recognition off: entries are `NOT_CHECKED`, and no alerts are raised.
- [ ] Recognition on, an enrolled consenting person walks in: `AUTHORIZED`, and no alert.
- [ ] A consenting person who is not enrolled walks in, face clearly visible: `UNAUTHORIZED` and an `unauthorized_entry` alert. With "Alarm on unauthorized" on, the alarm shows `simulated`.
- [ ] Walking in with the face turned away or covered, or too far away, gives `NEEDS_REVIEW` with a reason, a review alert and **no** alarm.
- [ ] Silence for 5 minutes: new alerts show `silenced`, and Re-arm ends it.
- [ ] **Test alarm** (administrator, password) records an `alarm_test` alert.
- [ ] Webhook (if configured): the receiver gets the JSON. It carries no names or images.

## 4. Physical relay (only after 3 passes)
- [ ] Set `ALARM_OUTPUT=http_relay` and the relay URLs in `.env`, then run `docker compose up -d api`. The Alerts page shows "Network relay", configured: yes.
- [ ] Test alarm: the siren sounds for `ALARM_DURATION_SECONDS`, then stops.
- [ ] Silence during a test: the siren stops at once.
- [ ] Unplug the relay and test again: the alert shows `failed`, with the error on the Alerts page.

## 5. Event footage
- [ ] In a face event, click the frame. After the export, the clip plays and covers the event plus about 5 s before and after.
- [ ] The Footage button on a crossing plays the moment of the crossing.
- [ ] An event older than `FRIGATE_RECORDING_DAYS` reports "footage has expired". A gap in the recording shows "No recording covers this time".
- [ ] A viewer cannot open footage (403).

## 6. Estimates and liveness
- [ ] Face-event detail and the Privacy page show attribute estimates as **unknown (no model installed)** and liveness as **not checked**. Nothing implies spoof detection.

## 7. Privacy and retention
- [ ] The Privacy page lists the retention periods from `.env` and the counts of stored data.
- [ ] Apply retention now: old rows are deleted, and an audit entry is written.
- [ ] Delete all reference embeddings: recognition switches off. Switching it on again recomputes the embeddings.
- [ ] Back up the database, `media/` and the key; restore them on a test copy. The gallery images open, which shows the key matches.
