# Alerts and the alarm output

## Alerts (always on)
Every alert is stored in the database and shown on the **Alerts** page (it refreshes every 5 s). An operator acknowledges each one, and that is audited.

| Kind | Raised for | Drives the alarm? |
|---|---|---|
| `unauthorized_entry` | A gate entry with verdict `UNAUTHORIZED` | Only on a line with "Alarm on unauthorized entry" switched on |
| `needs_review` | A gate entry with verdict `NEEDS_REVIEW` | Never |
| `alarm_test` | A manual test by an administrator | Yes (that is the test) |

**Delivery:**
- In-app, always.
- Optionally as a JSON POST to `ALERT_WEBHOOK_URL`, a LAN service. The payload carries the alert id, kind, camera, reason, alarm state and time. It never carries names, images or embeddings.
- `ALERT_WEBHOOK_REVIEW=false` stops review alerts from being sent to the webhook.
- The delivery result is stored with the alert.

## Alarm output (`ALARM_OUTPUT`)
| Value | What happens |
|---|---|
| `simulation` (default) | Nothing is switched. The alert records `simulated`, and the api logs `ALARM (simulation)`. |
| `http_relay` | A network relay on the LAN. The api requests `ALARM_RELAY_ON_URL` (GET or POST, optional basic auth), then `ALARM_RELAY_OFF_URL` after `ALARM_DURATION_SECONDS`, or as soon as an operator silences the alarm. |
| `none` | Alerts only. |

## Safety rules
- **Configuration.** A physical output is used only when an administrator has set `ALARM_OUTPUT=http_relay` and the relay URLs in `deploy/.env`. The api refuses to start with `http_relay` and no on-URL.
- **Relay and webhook addresses** must be **IP addresses inside `DEVICE_ALLOWED_NETWORKS`**: LAN only; host names, loopback and public addresses are refused. They are checked before every request, and redirects are not followed.
- **Per-line switch.** Each gate line has its own "Alarm on unauthorized entry" switch, off by default. Changing it needs the administrator's password and is audited.
- **Silence.** Operators can silence for up to `ALARM_MAX_SILENCE_MINUTES` (240) and re-arm early. Both are audited. While silenced, alerts are still recorded with alarm `silenced`.
- **Cooldown.** Within `ALARM_COOLDOWN_SECONDS` of the last activation, the output is not driven again (alarm `cooldown`).
- **Test.** Administrators can run a test after entering their password again. It ignores silence but not the cooldown, and is audited.
- **Failures.** A failed relay request is recorded as `failed`, shown on the Alerts page and logged. The alert itself is kept.

## Choosing a relay
Any relay with a plain HTTP on/off URL works, for example a LAN relay module with a REST API. Wire it to the siren or the NVR's alarm input according to the device's manual. Before relying on it:
1. Run **Test alarm** and confirm that the siren sounds and stops after the duration.
2. Silence during a test and confirm that it stops at once.
3. Unplug the relay and run the test again: the Alerts page must show `failed`.

The CP Plus NVR's own alarm output is not driven directly; no documented API for it was verified. **No relay or siren has been tested with this software yet.**
