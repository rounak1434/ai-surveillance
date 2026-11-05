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
