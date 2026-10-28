#!/usr/bin/env bash
# Build a release to install or update a counter or the cloud (run on the dev machine).
#
#   deploy/make-release.sh            -> releases/faida-<version>.tar.gz and .zip
#
# A release holds the backend source, the built screens (frontend/dist), deploy/ and
# docs/. Settings, the database, pictures and backups are never inside it, so an
# update or a rollback can't touch them.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$ROOT/backend/app/settings/config.py")"
NAME="faida-$VERSION"
OUT="$ROOT/releases"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "Building the screens..."
[ -d "$ROOT/frontend/node_modules" ] || npm --prefix "$ROOT/frontend" ci --silent
npm --prefix "$ROOT/frontend" run build --silent

mkdir -p "$WORK/$NAME/backend" "$WORK/$NAME/frontend" "$OUT"
cp -r "$ROOT/backend/app" "$ROOT/backend/migrations" "$WORK/$NAME/backend/"
cp "$ROOT/backend/alembic.ini" "$ROOT/backend/requirements.txt" "$ROOT/backend/pyproject.toml" \
   "$ROOT/backend/.env.example" "$ROOT/backend/.env.cloud.example" "$WORK/$NAME/backend/"
cp -r "$ROOT/frontend/dist" "$WORK/$NAME/frontend/"
cp -r "$ROOT/deploy" "$ROOT/docs" "$WORK/$NAME/"
find "$WORK/$NAME" -name __pycache__ -prune -exec rm -rf {} +
echo "$VERSION" > "$WORK/$NAME/VERSION"
# The PC clock must be later than this (the installer refuses a clock that is behind).
date -u +%Y-%m-%d > "$WORK/$NAME/BUILT"
git -C "$ROOT" rev-parse --short HEAD > "$WORK/$NAME/COMMIT" 2>/dev/null || true

tar -czf "$OUT/$NAME.tar.gz" -C "$WORK" "$NAME"
python3 - "$WORK" "$NAME" "$OUT/$NAME.zip" <<'PY'
import os, sys, zipfile
work, name, out = sys.argv[1:]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for folder, _, files in os.walk(os.path.join(work, name)):
        for f in files:
            path = os.path.join(folder, f)
            z.write(path, os.path.relpath(path, work))
PY
echo "Release ready:"
echo "  $OUT/$NAME.tar.gz   (Linux counter, cloud)"
echo "  $OUT/$NAME.zip      (Windows counter)"
