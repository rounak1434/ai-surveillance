# Accounts, roles, privacy and retention

## Roles
| Role | Can |
|---|---|
| viewer | See the live view, gate crossings (without names or images), alerts and the alarm state |
| operator | Everything a viewer can, plus: see face events, frames, crops and event footage; read people records and reference images (audited); take snapshots and clips; acknowledge alerts; silence the alarm |
| admin | Everything an operator can, plus: enroll and edit people; switch recognition; draw gate lines; test the alarm; set up cameras and Apply to Frigate; manage accounts; see the audit log; delete events and captures; run privacy actions |

**How roles are enforced:**
- The server enforces every role; the UI only hides what a role cannot use.
- Accounts that existed before roles were added became administrators.
- A role change or a disabled account takes effect at once, because the account's sessions are revoked.

**Accounts:**
- **Password change.** Under *My account*, a user can change their own password. It needs the current password, with the same lockout as sign-in. Every other session of that user is signed out.
- **Account management.** Administrators can create, disable, delete and reset accounts on the *Accounts* page. Every change needs their password again.
- **Last administrator.** The last active administrator cannot be disabled, demoted or deleted.
- **Administrator recovery.** If every administrator password is lost, run this on the host:
  ```
  cd /opt/ai-surveillance/deploy
  docker compose exec api ai-surveillance create-admin <username>
  ```
  It sets a new password and makes the account an active administrator. It signs that account out everywhere and is audited as `cli`. `ai-surveillance list-users` lists accounts and roles.

## Audit
**Audited changes:** gallery, recognition switch, accounts, gate lines, alarm (test, silence, re-arm), alert acknowledgements, privacy actions.

**Audited access:** opening a person's profile, viewing a reference image, viewing an event frame or crop, requesting and playing event footage.

Entries hold usernames, actions and ids only, never names, notes or images. Audit entries older than `AUDIT_RETENTION_DAYS` (365) are deleted.

## Retention (`deploy/.env`, applied hourly; 0 keeps until deleted by hand)
| Data | Setting | Default |
|---|---|---|
| Face events: rows, frames, crops, match results, estimates | `FACE_EVENT_RETENTION_DAYS` | 30 |
| Snapshots, clips and event footage | `CAPTURE_RETENTION_DAYS` | 0 |
| Gate crossings | `GATE_CROSSING_RETENTION_DAYS` | 90 |
| Alerts | `ALERT_RETENTION_DAYS` | 90 |
| Audit log | `AUDIT_RETENTION_DAYS` | 365 |
| Frigate recordings and snapshots | `record.continuous.days` / `snapshots.retain` in Frigate's config. Keep `FRIGATE_RECORDING_DAYS` equal to the first, so expired footage is reported as such. | 3 / 14 |
| Reference images and embeddings | Kept until the person or the image is deleted (People page) | — |

**Privacy page actions** (administrators):
- **Apply retention now**: runs every purge at once.
- **Delete all reference embeddings**: switches recognition off. The images stay, and switching recognition on again recomputes the embeddings.

Deleting a person removes their images, their embeddings and their link from past matches and crossings (`docs/GALLERY.md`).

## Encryption and backups
- **Encrypted:** reference images and embeddings, with AES-256-GCM under the credentials key (`CREDENTIALS_KEY`, or the key file `/data/credentials.key` in the api volume). It is the same key-management design as for camera passwords.
- **Not encrypted:** face-event frames, crops, captures and Frigate's recordings are plain files. Use full-disk encryption (LUKS) on the host.
- **A complete backup** needs three things:
  1. `ai-surveillance db backup`: the database, made consistently while the api runs.
  2. The api volume's `media/` directory, especially `media/gallery`.
  3. The credentials key.

  Store the key **separately** from the backups. Without it, the gallery cannot be decrypted. Anyone who has both can read it.
- **Restore** (`docs/DATABASE.md`):
  1. Stop the api.
  2. `ai-surveillance db restore FILE --yes`.
  3. Put `media/` and the key back.
  4. Start the api.
- **Deleted people stay in backups** until those backups are deleted. Keep backups no longer than the retention you promise.

## Face attribute estimates and liveness
No attribute or presentation-attack model is installed:
- Estimates for age range, gender presentation, expression, glasses, beard and mask are shown as **unknown**.
- The liveness check is shown as **unavailable**. The system cannot tell a photo or screen of an enrolled person from the person.

The contract for adding a model is in `backend/ai_surveillance/attributes.py`. Estimates are labelled as fallible model guesses and are never used for authorization, gate verdicts or alarms.
