#!/usr/bin/env bash
# Desktop shortcut that opens the local console in the default browser (Ubuntu, GNOME).
# Run as the desktop user, not with sudo:
#   deploy/desktop/install-desktop-shortcut.sh                    # name and address from deploy/.env
#   deploy/desktop/install-desktop-shortcut.sh "SAIL Console" https://192.168.1.50/
# Creates ~/.local/share/applications/ai-surveillance-console.desktop (app menu) and a copy on the
# Desktop, marked as trusted so GNOME runs it on double-click. Nothing else is changed.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$HERE/../.env"

env_value() {  # read one variable from deploy/.env without sourcing it (it holds secrets)
  [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1 | tr -d '\r' || true
}

NAME="${1:-$(env_value APP_DISPLAY_NAME)}"
NAME="${NAME:-AI Surveillance}"
SITE="$(env_value SITE_ADDRESS)"
URL="${2:-https://${SITE:-localhost}/}"

case "$URL" in
  https://*|http://*) ;;
  *) echo "The address must start with https:// or http://" >&2; exit 1 ;;
esac
case "$NAME$URL" in
  *$'\n'*|*\"*|*\`*|*\$*) echo "Name and address must not contain quotes, \$ or backticks" >&2; exit 1 ;;
esac

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
FILE="ai-surveillance-console.desktop"
mkdir -p "$APPS"

cat > "$APPS/$FILE" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=$NAME
Comment=Open the local surveillance console
Exec=xdg-open "$URL"
Icon=security-high
Terminal=false
Categories=Network;Security;
EOF
chmod 755 "$APPS/$FILE"

if [ -d "$DESKTOP_DIR" ]; then
  cp "$APPS/$FILE" "$DESKTOP_DIR/$FILE"
  chmod 755 "$DESKTOP_DIR/$FILE"
  # GNOME asks before running untrusted launchers; mark this one as trusted.
  gio set "$DESKTOP_DIR/$FILE" metadata::trusted true 2>/dev/null || true
fi
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true

echo "Shortcut \"$NAME\" -> $URL"
echo "  menu:    $APPS/$FILE"
[ -d "$DESKTOP_DIR" ] && echo "  desktop: $DESKTOP_DIR/$FILE (right-click > Allow Launching if GNOME still asks)"
echo "The browser warns about the certificate until Caddy's local CA is trusted (docs/OPERATIONS.md)."
