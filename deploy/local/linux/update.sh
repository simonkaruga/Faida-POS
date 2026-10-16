#!/usr/bin/env bash
# Update a Linux counter, after closing hours only (masterplan 7.1):
#
#   sudo ./update.sh faida-0.3.0.tar.gz [--force]
#
# backup -> install the new version beside the old -> migrate -> health check.
# If anything fails, it rolls back by itself: the database migrations are undone (or,
# failing that, the backup taken a minute earlier is restored) and the old version is
# started again. --force updates even with shifts or bills still open.
set -euo pipefail
ARCHIVE="${1:?Usage: update.sh faida-<version>.tar.gz [--force]}"
FORCE="${2:-}"
[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }

BASE=/opt/faida
# The cloud uses this same script (deploy/cloud/update.sh sets these).
SERVICE="${FAIDA_SERVICE:-faida-counter}"
ENV_FILE="${FAIDA_ENV:-/etc/faida/counter.env}"
HEALTH="${FAIDA_HEALTH_URL:-http://127.0.0.1:8000/api/health}"
UNITS="${FAIDA_UNITS:-deploy/local/linux}"
OLD="$(readlink -f "$BASE/current")"
OLD_VERSION="$(cat "$OLD/VERSION")"
LOG=/var/lib/faida/update-$(date +%Y%m%d-%H%M%S).log
exec > >(tee -a "$LOG") 2>&1

py() { local dir="$1"; shift; (cd "$dir/backend" && sudo -u faida env FAIDA_ENV_FILE="$ENV_FILE" .venv/bin/python "$@"); }
say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

say "Checking the counter is closed"
if [ "$FORCE" != "--force" ] && [ "$SERVICE" = faida-counter ]; then py "$OLD" -m app.ops busy; fi

say "Unpacking"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
tar -xzf "$ARCHIVE" -C "$WORK"
SRC="$(find "$WORK" -mindepth 1 -maxdepth 1 -type d | head -1)"
NEW_VERSION="$(cat "$SRC/VERSION")"
NEW="$BASE/releases/$NEW_VERSION"
[ "$NEW" != "$OLD" ] || { echo "Version $NEW_VERSION is already running."; exit 1; }
rm -rf "$NEW"
cp -r "$SRC" "$NEW"
python3 -m venv "$NEW/backend/.venv"
"$NEW/backend/.venv/bin/pip" install -q --disable-pip-version-check -r "$NEW/backend/requirements.txt"

say "Backup before updating"
BACKUP="$(py "$OLD" -m app.backup create --to /var/lib/faida/update-backups --keep 5 2>&1 | sed -n 's/^Backup written: //p')"
[ -n "$BACKUP" ] || { echo "The backup failed; nothing was changed."; exit 1; }
echo "$BACKUP"
OLD_REVISION="$(py "$OLD" -m app.ops revision)"

rollback() {
  say "Update failed: rolling back to $OLD_VERSION"
  systemctl stop "$SERVICE" || true
  if ! py "$NEW" -m alembic downgrade "$OLD_REVISION"; then
    echo "Undoing the migrations failed; restoring the backup taken before the update."
    py "$OLD" -m app.backup restore --file "$BACKUP" >/dev/null
  fi
  ln -sfn "$OLD" "$BASE/current"
  systemctl start "$SERVICE"
  if py "$OLD" -m app.ops wait-healthy --url "$HEALTH" --version "$OLD_VERSION" --seconds 60; then
    echo "Rolled back. $OLD_VERSION is running again; nothing was lost. Log: $LOG"
  else
    echo "ROLLBACK DID NOT COME BACK HEALTHY. Call Avinaya. Backup: $BACKUP  Log: $LOG"
  fi
  exit 1
}
trap 'rollback' ERR

say "Switching to $NEW_VERSION"
systemctl stop "$SERVICE"
ln -sfn "$NEW" "$BASE/current"
py "$NEW" -m alembic upgrade head
systemctl start "$SERVICE"
py "$NEW" -m app.ops wait-healthy --url "$HEALTH" --version "$NEW_VERSION" --seconds 90
trap - ERR

# Pick up changed service files, and keep the three newest releases.
cp "$NEW/$UNITS/"faida-*.service "$NEW/$UNITS/"faida-*.timer /etc/systemd/system/
systemctl daemon-reload
ls -1dt "$BASE/releases/"*/ | tail -n +4 | grep -v "$NEW" | grep -v "$OLD" | xargs -r rm -rf
say "Updated $OLD_VERSION -> $NEW_VERSION. Log: $LOG"
