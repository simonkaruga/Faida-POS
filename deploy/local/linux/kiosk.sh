#!/usr/bin/env bash
# Opens the counter full-screen once the backend answers (started at login by the
# autostart entry the installer writes). Staff can't leave it; Alt+F4 then this
# script reopens it.
URL="${FAIDA_URL:-http://localhost:8000}"
for _ in $(seq 1 60); do curl -fs "$URL/api/health" >/dev/null && break; sleep 2; done
command -v xset >/dev/null && { xset s off; xset -dpms; xset s noblank; } 2>/dev/null
BROWSER="$(command -v chromium || command -v chromium-browser || command -v google-chrome || command -v google-chrome-stable)"
PROFILE="$HOME/.config/faida-kiosk"
while true; do
  if [ -n "$BROWSER" ]; then
    "$BROWSER" --kiosk --app="$URL" --user-data-dir="$PROFILE" --no-first-run --noerrdialogs \
      --disable-infobars --disable-session-crashed-bubble --disable-translate \
      --overscroll-history-navigation=0 --disable-pinch --check-for-update-interval=31536000
  else
    firefox --kiosk "$URL"
  fi
  sleep 2
done
