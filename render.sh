#!/usr/bin/env bash
# Render the CV sources in this folder to single-page PDFs in ./out/.
#
#   ./render.sh              # render every cv*.html next to this script
#   ./render.sh mine.html    # render just one
#
# Each source measures its own rendered height and declares a matching @page
# size, so Chrome emits the whole CV as one tall page instead of paginating it.

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$DIR/out"

# Chrome is found via $CHROME, then the usual install paths per platform.
find_chrome() {
  if [ -n "${CHROME:-}" ]; then
    echo "$CHROME"
    return
  fi
  local candidates=(
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    "/Applications/Chromium.app/Contents/MacOS/Chromium"
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
  )
  local c
  for c in "${candidates[@]}"; do
    [ -x "$c" ] && { echo "$c"; return; }
  done
  for c in google-chrome google-chrome-stable chromium chromium-browser microsoft-edge; do
    command -v "$c" >/dev/null 2>&1 && { command -v "$c"; return; }
  done
}

CHROME_BIN="$(find_chrome)"
if [ -z "$CHROME_BIN" ]; then
  echo "No Chrome/Chromium found. Set CHROME=/path/to/chrome and retry." >&2
  exit 1
fi

mkdir -p "$OUT"

sources=("$@")
if [ ${#sources[@]} -eq 0 ]; then
  sources=("$DIR"/cv*.html)
  if [ ! -e "${sources[0]}" ]; then
    echo "No cv*.html found. Copy template.html to cv.html and edit it." >&2
    exit 1
  fi
fi

for src in "${sources[@]}"; do
  [ -f "$src" ] || src="$DIR/$src"
  # file:// needs an absolute path; a relative one silently renders a blank
  # page at Chrome's default paper size.
  src="$(cd "$(dirname "$src")" && pwd)/$(basename "$src")"
  out="$OUT/$(basename "${src%.html}").pdf"

  "$CHROME_BIN" \
    --headless \
    --disable-gpu \
    --no-pdf-header-footer \
    --run-all-compositor-stages-before-draw \
    --virtual-time-budget=4000 \
    --print-to-pdf="$out" \
    "file://$src" 2>/dev/null

  pages=$(LC_ALL=C grep -a -o '/Count [0-9]*' "$out" | head -1 | tr -dc '0-9')
  size=$(LC_ALL=C grep -a -o '/MediaBox[^]]*]' "$out" | head -1)

  echo "out/$(basename "$out"): ${pages:-?} page(s), $size"
  [ "${pages:-1}" = "1" ] || echo "  WARNING: expected a single page" >&2
done
