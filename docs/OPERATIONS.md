# Operating the stack on Ubuntu

The application runs as Docker containers: frigate, mosquitto, api, inference and web. A systemd unit starts them at boot. The console is the web UI, served by the `web` container (Caddy) over HTTPS.

## Install (once)
1. **Put the repository** at `/opt/ai-surveillance` and set up `deploy/.env`. See docs/SETUP.md for Docker, the NVIDIA toolkit and `.env`.
   - `chmod 600 deploy/.env`.
   - Set `APP_DISPLAY_NAME`, for example "SAIL Gate Monitoring".
   - Set `SITE_ADDRESS`.
2. **Build and start once by hand:**
   ```
   cd /opt/ai-surveillance/deploy
   docker compose up -d --build
   docker compose ps          # all services "running" / "healthy"
   ```
3. **Create the first administrator:**
   ```
   docker compose exec api ai-surveillance create-admin <username>
   ```
4. **Start at boot and after a power cut:**
   ```
   sudo deploy/install-service.sh
   ```
   This installs and enables `ai-surveillance.service` and enables `docker.service`. Every container also has `restart: unless-stopped`.

   In the PC's BIOS/UEFI, set **"Restore on AC power loss" = Power On**. Without it, the PC stays off after a power cut, and nothing in software can change that.
5. **Desktop shortcut** (as the desktop user, not root):
   ```
   deploy/desktop/install-desktop-shortcut.sh
   ```
   It reads `APP_DISPLAY_NAME` and `SITE_ADDRESS` from `deploy/.env`, or takes them as arguments, for example `"SAIL Console" https://192.168.1.50/`. It adds the console to the app menu and to the desktop.
6. **Trust Caddy's local certificate authority** so the browser does not warn. Export it from the container:
   ```
   docker compose cp web:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt
   ```
   Then import it into the browser's certificate store (Firefox: Settings → Privacy & Security → Certificates → Import), or install it system-wide with `sudo cp caddy-root.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates`.

## Daily use
| Task | Command |
|---|---|
| Start | `sudo systemctl start ai-surveillance` |
| Stop (keeps all data) | `sudo systemctl stop ai-surveillance` |
| Status | `systemctl status ai-surveillance` and `docker compose -f /opt/ai-surveillance/deploy/compose.yaml ps` |
| Logs of one service | `docker compose -f /opt/ai-surveillance/deploy/compose.yaml logs --tail 200 api` |
| Restart one service | `docker compose -f /opt/ai-surveillance/deploy/compose.yaml restart api` |
| Health check | `deploy/doctor.sh` |

## Recovery
- **The console does not open.** Run `docker compose ps`. If `web` or `api` is not healthy, read its logs. A 502 in the browser means the api is down or restarting.
- **"Events delayed" in the top bar.** MQTT is disconnected. Check `docker compose logs mosquitto frigate`; Frigate logs MQTT connection errors. Face events still arrive through polling, but gate crossings are not counted until MQTT is back.
- **After a power cut.** The unit retries every 15 s until Docker is ready. If a service stays unhealthy, run `docker compose up -d` once. SQLite and the WAL recover on their own; to check, run `docker compose exec api ai-surveillance db verify /data/app.db`.
- **Lost administrator password.** Run `docker compose exec api ai-surveillance create-admin <username>` (docs/PRIVACY.md).
- **Damaged database.** Stop the api and restore the newest backup (docs/DATABASE.md). Then put `media/` and the credentials key back.
- **The alarm sounds unexpectedly.** Silence it on the Alerts page. To disable the output entirely, set `ALARM_OUTPUT=simulation` in `.env` and run `docker compose up -d api`.

## Updating
```
cd /opt/ai-surveillance && git pull --ff-only
cd deploy && docker compose exec api ai-surveillance db backup && docker compose up -d --build
```
Migrations run at api start, and the database is backed up first (docs/DATABASE.md).
