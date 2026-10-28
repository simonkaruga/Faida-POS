#!/usr/bin/env bash
# Build releases/FaidaSetup-<version>.exe: a single Windows installer that needs no
# internet on site. It carries the release, the Windows Python packages, and the
# PostgreSQL 16 and Python 3.12 installers. Run on the dev machine (Linux):
#
#   deploy/make-windows-setup.sh
#
# Needs internet the first time (downloads are cached in releases/windows-cache), the
# backend's .venv (its package versions are the tested ones), and NSIS: `makensis` on
# the PATH, or it is unpacked from Ubuntu's nsis package into the cache (no root needed).
# Also makes releases/USB: the .exe, its checksum and the installation guide as a PDF
# (printed with Chrome), ready to copy to a USB stick.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$ROOT/backend/app/settings/config.py")"
CACHE="$ROOT/releases/windows-cache"
PYTHON_VERSION=3.12.10       # the last 3.12 with a Windows installer
PG_VERSION=16.15-1           # same major as development and the tests
PY_EXE="python-$PYTHON_VERSION-amd64.exe"
PG_EXE="postgresql-$PG_VERSION-windows-x64.exe"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$CACHE"

"$ROOT/deploy/make-release.sh" >/dev/null
echo "Release $VERSION built."
python3 -c "import zipfile, sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" \
  "$ROOT/releases/faida-$VERSION.zip" "$WORK"
RELEASE="$WORK/faida-$VERSION"

echo "Windows Python packages (the tested versions)..."
[ -x "$CACHE/tools/bin/uv" ] || { python3 -m venv "$CACHE/tools" && "$CACHE/tools/bin/pip" install -q uv; }
"$ROOT/backend/.venv/bin/pip" freeze --exclude-editable > "$WORK/tested.txt"
"$CACHE/tools/bin/uv" pip compile -q "$ROOT/backend/requirements.txt" -c "$WORK/tested.txt" \
  --python-platform x86_64-pc-windows-msvc --python-version 3.12 --no-header --no-annotate -o "$WORK/windows.txt"
"$ROOT/backend/.venv/bin/pip" download -q --no-deps --only-binary=:all: --platform win_amd64 \
  --python-version 3.12 --implementation cp -r "$WORK/windows.txt" -d "$RELEASE/backend/wheels"
echo "  $(ls "$RELEASE/backend/wheels" | wc -l) packages"

echo "PostgreSQL and Python installers..."
mkdir -p "$WORK/bundle"
[ -f "$CACHE/$PY_EXE" ] || curl -fL -o "$CACHE/$PY_EXE" "https://www.python.org/ftp/python/$PYTHON_VERSION/$PY_EXE"
[ -f "$CACHE/$PG_EXE" ] || curl -fL -o "$CACHE/$PG_EXE" "https://get.enterprisedb.com/postgresql/$PG_EXE"
cp "$CACHE/$PY_EXE" "$CACHE/$PG_EXE" "$WORK/bundle/"

MAKENSIS="$(command -v makensis || true)"
if [ -z "$MAKENSIS" ]; then
  if [ ! -x "$CACHE/nsis/usr/bin/makensis" ]; then
    echo "Unpacking NSIS into the cache..."
    (cd "$CACHE" && apt-get download nsis nsis-common >/dev/null && for d in nsis*.deb; do dpkg -x "$d" nsis; done && rm -f nsis*.deb)
  fi
  MAKENSIS="$CACHE/nsis/usr/bin/makensis"
  export NSISDIR="$CACHE/nsis/usr/share/nsis"
fi

OUT="$ROOT/releases/FaidaSetup-$VERSION.exe"
echo "Building the installer (a few minutes)..."
"$MAKENSIS" -V2 -DVERSION="$VERSION" -DRELEASE_DIR="$RELEASE" -DBUNDLE_DIR="$WORK/bundle" -DOUTFILE="$OUT" \
  "$ROOT/deploy/local/windows/faida-setup.nsi"
echo "Windows installer ready: $OUT ($(du -h "$OUT" | cut -f1))"
sha256sum "$OUT" | cut -d' ' -f1 > "$OUT.sha256"
echo "  sha256 $(cat "$OUT.sha256")"

USB="$ROOT/releases/USB"
rm -rf "$USB" && mkdir -p "$USB"
cp "$OUT" "$OUT.sha256" "$USB/"
# The check tool, to run on a counter when something is wrong (report saved on the stick).
cp "$ROOT/deploy/local/windows/Faida-Check.bat" "$USB/"
cp "$ROOT/deploy/local/windows/check.ps1" "$USB/Faida-Check.ps1"
# The sample menu, for a counter whose menu is still empty.
cp "$ROOT/deploy/local/windows/Load-Demo-Menu.bat" "$USB/"
cp "$ROOT/deploy/local/windows/load-demo-menu.ps1" "$USB/Load-Demo-Menu.ps1"
CHROME="$(command -v google-chrome || command -v chromium || command -v chromium-browser || true)"
if [ -n "$CHROME" ]; then
  "$CHROME" --headless=new --no-pdf-header-footer --print-to-pdf="$USB/Faida-POS-Installation-Guide.pdf" \
    "file://$ROOT/docs/windows-install-guide.html" 2>/dev/null
else
  cp "$ROOT/docs/windows-install-guide.html" "$USB/"
  echo "  (no Chrome: copied the guide as HTML; open it and print to PDF)"
fi
echo "Copy this folder to the USB stick: $USB"
ls -lh "$USB" | tail -n +2
