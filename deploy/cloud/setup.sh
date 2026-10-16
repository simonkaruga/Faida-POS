#!/usr/bin/env bash
# Set up the shared Faida cloud on a fresh Ubuntu 24.04 server (one for all clients,
# masterplan 7.2). From an unpacked release, as root:
#
#   sudo ./deploy/cloud/setup.sh faida.co.ke admin@avinaya.co.ke
#
# Point the domain's DNS A record at the server first (TLS needs it).
# Safe to run again: the settings and database are kept.
set -euo pipefail
DOMAIN="${1:?Usage: setup.sh <domain> <email for TLS notices>}"
EMAIL="${2:?Usage: setup.sh <domain> <email for TLS notices>}"
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }

RELEASE="$(cd "$(dirname "$0")/../.." && pwd)"
VERSION="$(cat "$RELEASE/VERSION")"
BASE=/opt/faida
ENV_FILE=/etc/faida/cloud.env
STATE=/var/lib/faida
say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

say "1/7 Packages"
apt-get update -qq
apt-get install -y -qq postgresql python3 python3-venv python3-pip nginx certbot python3-certbot-nginx ufw curl >/dev/null

say "2/7 Firewall: SSH and HTTPS only"
ufw allow OpenSSH >/dev/null
ufw allow 'Nginx Full' >/dev/null
ufw --force enable >/dev/null

say "3/7 Account, folders, database"
id faida >/dev/null 2>&1 || useradd --system --home-dir "$STATE" --shell /usr/sbin/nologin faida
mkdir -p "$BASE/releases" /etc/faida "$STATE/update-backups" /var/backups/faida
chown -R faida:faida "$STATE" /var/backups/faida
chmod 700 /var/backups/faida
systemctl enable --now postgresql >/dev/null
sudo -u postgres psql -qtAc "SELECT 1 FROM pg_roles WHERE rolname='faida'" | grep -q 1 || sudo -u postgres createuser faida
sudo -u postgres psql -qtAc "SELECT 1 FROM pg_database WHERE datname='faida'" | grep -q 1 || sudo -u postgres createdb -O faida faida

say "4/7 Faida $VERSION"
TARGET="$BASE/releases/$VERSION"
[ "$RELEASE" = "$TARGET" ] || { rm -rf "$TARGET"; cp -r "$RELEASE" "$TARGET"; }
python3 -m venv "$TARGET/backend/.venv"
"$TARGET/backend/.venv/bin/pip" install -q --disable-pip-version-check -r "$TARGET/backend/requirements.txt"
ln -sfn "$TARGET" "$BASE/current"

say "5/7 Settings ($ENV_FILE)"
if [ ! -f "$ENV_FILE" ]; then
  while true; do
    read -rsp "Backup passphrase for the cloud (keep it in Avinaya's password manager): " PASS; echo
    read -rsp "Type it again: " PASS2; echo
    [ -n "$PASS" ] && [ "$PASS" = "$PASS2" ] && break
    echo "Empty, or they don't match."
  done
  read -rp "Alert webhook for health alerts (Slack/Teams/ntfy URL, empty: log only): " WEBHOOK
  umask 077
  cat > "$ENV_FILE" <<CONF
FAIDA_MODE=cloud
FAIDA_DATABASE_URL=postgresql+psycopg://faida@/faida
# Signs owner phone logins. Unique to the cloud; never share it.
FAIDA_PIN_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
FAIDA_TIMEZONE=Africa/Nairobi
FAIDA_STATE_DIR=$STATE
FAIDA_STATIC_DIR=$BASE/current/frontend/dist
FAIDA_BACKUP_PASSPHRASE=$PASS
# Avinaya's token for https://$DOMAIN/api/admin/health
FAIDA_ADMIN_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
FAIDA_ALERT_WEBHOOK=$WEBHOOK
CONF
  chown root:faida "$ENV_FILE"; chmod 640 "$ENV_FILE"
fi
(cd "$BASE/current/backend" && sudo -u faida env FAIDA_ENV_FILE="$ENV_FILE" .venv/bin/python -m alembic upgrade head)

say "6/7 Services: app, daily backup, hourly health check"
cp "$RELEASE/deploy/cloud/"faida-*.service "$RELEASE/deploy/cloud/"faida-*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now faida-cloud.service faida-cloud-backup.timer faida-health.timer
(cd "$BASE/current/backend" && .venv/bin/python -m app.ops wait-healthy --url http://127.0.0.1:8100/api/health --version "$VERSION" --seconds 60)

say "7/7 Web server and TLS for $DOMAIN"
sed "s/DOMAIN/$DOMAIN/" "$RELEASE/deploy/cloud/nginx-faida.conf" > /etc/nginx/sites-available/faida
ln -sfn /etc/nginx/sites-available/faida /etc/nginx/sites-enabled/faida
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
certbot --nginx -n --agree-tos -m "$EMAIL" -d "$DOMAIN" --redirect

cat <<DONE

The Faida cloud $VERSION is running: https://$DOMAIN
  Settings: $ENV_FILE  (the admin token is in it)
  Backups:  /var/backups/faida, daily at 02:15 (set up rclone remote "offsite" to copy them off the server)
  Logs:     journalctl -u faida-cloud -f
Next, for each client (deploy/cloud/README.md):
  cd $BASE/current/backend && sudo -u faida env FAIDA_ENV_FILE=$ENV_FILE .venv/bin/python -m app.cli register-device --business-id <id from the counter>
DONE
