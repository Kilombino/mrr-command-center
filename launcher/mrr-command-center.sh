#!/usr/bin/env bash
# Launch the MRR Command Center as a standalone window (Chromium app mode).
# Uses its own profile dir so the dashboard login cookie persists between launches.
URL="http://127.0.0.1:7160/"
PROFILE="$HOME/.config/mrr-command-center"
mkdir -p "$PROFILE"
if command -v chromium >/dev/null 2>&1; then
  exec chromium --app="$URL" --user-data-dir="$PROFILE" --class=MRRCommandCenter --window-size=1600,1000 \
    --no-first-run --no-default-browser-check --disable-features=Translate,TranslateUI "$@"
else
  exec xdg-open "$URL"
fi
