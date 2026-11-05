#!/usr/bin/env bash
# Install the systemd unit so the stack starts at boot and after a power cut.
#   sudo deploy/install-service.sh            # repository at /opt/ai-surveillance (the default)
#   sudo deploy/install-service.sh /srv/app   # repository somewhere else
# Changes only: /etc/systemd/system/ai-surveillance.service, and enables docker + that unit.
# It does not start or stop anything; start with: sudo systemctl start ai-surveillance
set -euo pipefail

ROOT="${1:-/opt/ai-surveillance}"
UNIT=/etc/systemd/system/ai-surveillance.service

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo." >&2
  exit 1
fi
if [ ! -f "$ROOT/deploy/compose.yaml" ]; then
  echo "No $ROOT/deploy/compose.yaml: give the repository path as the first argument." >&2
  exit 1
fi
if [ ! -f "$ROOT/deploy/.env" ]; then
  echo "No $ROOT/deploy/.env yet: copy .env.example and fill it in first (docs/SETUP.md)." >&2
  exit 1
fi

sed "s#^WorkingDirectory=.*#WorkingDirectory=$ROOT/deploy#" "$ROOT/deploy/systemd/ai-surveillance.service" > "$UNIT"
chmod 644 "$UNIT"
systemctl daemon-reload
systemctl enable docker.service
systemctl enable ai-surveillance.service
echo "Installed $UNIT (WorkingDirectory=$ROOT/deploy) and enabled it at boot."
echo "Start now:  sudo systemctl start ai-surveillance"
echo "Status:     systemctl status ai-surveillance; docker compose -f $ROOT/deploy/compose.yaml ps"
