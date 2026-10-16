#!/usr/bin/env bash
# Install Faida on a Linux counter PC (Ubuntu 22.04/24.04 or Debian 12). Run from an
# unpacked release, as root:
#
#   sudo ./deploy/local/linux/install.sh [--kiosk-user counter] [--lan]
#
#   --kiosk-user   the desktop account that logs in automatically and shows the counter
#                  full-screen (default: the account that ran sudo)
#   --lan          also serve the screens on the local network (Android touch screen,
#                  second terminal). Without it only this PC can open them.
#
# Safe to run again: existing settings, database and pictures are kept.
set -euo pipefail

KIOSK_USER="${SUDO_USER:-}"
HOST=127.0.0.1
while [ $# -gt 0 ]; do
  case "$1" in
    --kiosk-user) KIOSK_USER="$2"; shift 2 ;;
    --lan) HOST=0.0.0.0; shift ;;
    *) echo "Unknown option $1"; exit 2 ;;
  esac
done
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }

RELEASE="$(cd "$(dirname "$0")/../../.." && pwd)"
VERSION="$(cat "$RELEASE/VERSION")"
BASE=/opt/faida
ENV_FILE=/etc/faida/counter.env
STATE=/var/lib/faida
USB=/mnt/faida-usb
HERE="$RELEASE/deploy/local/linux"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

say "1/8 Packages (PostgreSQL, Python)"
apt-get update -qq
apt-get install -y -qq postgresql python3 python3-venv python3-pip curl >/dev/null

say "2/8 Service account and folders"
id faida >/dev/null 2>&1 || useradd --system --home-dir "$STATE" --shell /usr/sbin/nologin faida
usermod -aG lp,dialout faida  # USB receipt printers show up as /dev/usb/lp0 (group lp)
mkdir -p "$BASE/releases" /etc/faida "$STATE/images" "$STATE/update-backups" "$USB"
chown -R faida:faida "$STATE"

say "3/8 Database"
systemctl enable --now postgresql >/dev/null
sudo -u postgres psql -qtAc "SELECT 1 FROM pg_roles WHERE rolname='faida'" | grep -q 1 \
  || sudo -u postgres createuser faida
sudo -u postgres psql -qtAc "SELECT 1 FROM pg_database WHERE datname='faida'" | grep -q 1 \
  || sudo -u postgres createdb -O faida faida

say "4/8 Faida $VERSION"
TARGET="$BASE/releases/$VERSION"
if [ "$RELEASE" != "$TARGET" ]; then
  rm -rf "$TARGET"
  cp -r "$RELEASE" "$TARGET"
fi
python3 -m venv "$TARGET/backend/.venv"
"$TARGET/backend/.venv/bin/pip" install -q --disable-pip-version-check -r "$TARGET/backend/requirements.txt"
ln -sfn "$TARGET" "$BASE/current"

say "5/8 Settings ($ENV_FILE)"
if [ ! -f "$ENV_FILE" ]; then
  read -rp "Counter printer [device:/dev/usb/lp0]: " COUNTER_PRINTER
  read -rp "Kitchen printer, e.g. network:192.168.1.50 [same as counter]: " KITCHEN_PRINTER
  while true; do
    read -rsp "Backup passphrase (write it down and keep it AWAY from the counter): " PASS; echo
    read -rsp "Type it again: " PASS2; echo
    [ -n "$PASS" ] && [ "$PASS" = "$PASS2" ] && break
    echo "Empty, or they don't match. Try again."
  done
  read -rp "Cloud URL, e.g. https://faida.co.ke (empty: link later): " CLOUD_URL
  CLOUD_TOKEN=""
  [ -n "$CLOUD_URL" ] && read -rp "Counter token from 'register-device' on the cloud: " CLOUD_TOKEN
  umask 077
  cat > "$ENV_FILE" <<CONF
FAIDA_MODE=local
FAIDA_DATABASE_URL=postgresql+psycopg://faida@/faida
# Protects staff PINs. It is inside every backup; never share it.
FAIDA_PIN_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
FAIDA_TIMEZONE=Africa/Nairobi
FAIDA_STATE_DIR=$STATE
FAIDA_STATIC_DIR=$BASE/current/frontend/dist
FAIDA_COUNTER_PRINTER=${COUNTER_PRINTER:-device:/dev/usb/lp0}
FAIDA_KITCHEN_PRINTER=${KITCHEN_PRINTER:-${COUNTER_PRINTER:-device:/dev/usb/lp0}}
FAIDA_BACKUP_PASSPHRASE=$PASS
FAIDA_CLOUD_URL=$CLOUD_URL
FAIDA_CLOUD_TOKEN=$CLOUD_TOKEN
# Email the daily closing (optional). Gmail: smtp.gmail.com, 587, an app password.
FAIDA_SMTP_HOST=
FAIDA_SMTP_PORT=587
FAIDA_SMTP_USER=
FAIDA_SMTP_PASSWORD=
FAIDA_SMTP_FROM=
CONF
  chown root:faida "$ENV_FILE"
  chmod 640 "$ENV_FILE"
else
  echo "Keeping the existing settings."
fi
echo "FAIDA_HOST=$HOST" > /etc/faida/listen.env

run() { (cd "$BASE/current/backend" && sudo -u faida env FAIDA_ENV_FILE="$ENV_FILE" .venv/bin/python "$@"); }
run -m alembic upgrade head

say "6/8 Business, owner and menu"
if ! run -m app.ops set-up 2>/dev/null; then
  read -rp "Business name (as on receipts): " NAME
  read -rp "Owner's name: " OWNER
  run -m app.cli init-business --name "$NAME" --owner "$OWNER"
  read -rp "Menu file to load (JSON, empty to enter it on the counter later): " MENU
  [ -n "$MENU" ] && run -m app.cli load-menu "$(realpath "$MENU")"
else
  echo "Business already set up."
fi

say "7/8 Services: start at boot, nightly backup to the USB drive"
cp "$HERE/faida-counter.service" "$HERE/faida-backup.service" "$HERE/faida-backup.timer" /etc/systemd/system/
grep -q "LABEL=FAIDABACKUP" /etc/fstab || \
  echo "LABEL=FAIDABACKUP $USB auto nofail,noauto,x-systemd.automount,x-systemd.device-timeout=5s,uid=faida,gid=faida,umask=077 0 0" >> /etc/fstab
systemctl daemon-reload
systemctl enable --now faida-counter.service faida-backup.timer
run -m app.ops wait-healthy --version "$VERSION" --seconds 60

say "8/8 Full-screen counter at login"
if [ -n "$KIOSK_USER" ] && id "$KIOSK_USER" >/dev/null 2>&1; then
  HOME_DIR="$(getent passwd "$KIOSK_USER" | cut -d: -f6)"
  mkdir -p "$HOME_DIR/.config/autostart"
  cat > "$HOME_DIR/.config/autostart/faida-kiosk.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Faida counter
Exec=$BASE/current/deploy/local/linux/kiosk.sh
X-GNOME-Autostart-enabled=true
DESK
  chown -R "$KIOSK_USER:" "$HOME_DIR/.config/autostart"
  echo "The counter opens full-screen when $KIOSK_USER logs in."
  echo "Turn on automatic login for $KIOSK_USER in Settings > Users."
else
  echo "No desktop user given (--kiosk-user); skipped."
fi

cat <<DONE

Faida $VERSION is installed and running: http://localhost:8000
  Settings:  $ENV_FILE   (printers, cloud link, email)
  Pictures and backup status: $STATE
  Backups:   every night at 04:30 to a USB drive labelled FAIDABACKUP
             (format it and name it FAIDABACKUP; check with: sudo systemctl start faida-backup)
  Logs:      journalctl -u faida-counter -f
  Update:    sudo $BASE/current/deploy/local/linux/update.sh faida-<version>.tar.gz
Now follow docs/install-checklist.md from step 3.
DONE
