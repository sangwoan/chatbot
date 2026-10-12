#!/usr/bin/env bash
# Prepares the page exactly as the app serves it: copies the web app into OUT_DIR, drops the Google Fonts
# link (the bundled fonts/ cover it), locks the page to its own origin with a CSP and records the web build
# number in bundle.json. Used by build-apk.sh (bundled in the APK) and publish-update.sh (web updates).
# Usage: web-assets.sh OUT_DIR WEB_BUILD
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WEB="$HERE/../../retro-camera"
OUT_DIR="$1"
WEB_BUILD="$2"

mkdir -p "$OUT_DIR"
cp "$WEB/index.html" "$WEB/icon.svg" "$OUT_DIR/"
rm -rf "$OUT_DIR/fonts" && cp -R "$WEB/fonts" "$OUT_DIR/fonts"
python3 - "$OUT_DIR/index.html" <<'PY'
import re, sys
p = sys.argv[1]
s = open(p, encoding='utf-8').read()
s = re.sub(r'\n?<link[^>]+fonts\.(googleapis|gstatic)\.com[^>]*>', '', s)
# The page itself never talks to the network: lock it to its own origin.
csp = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' blob: data:; media-src 'self' blob: mediastream:; font-src 'self' data:; "
       "connect-src 'self' blob: data:; worker-src 'none'; frame-src 'none'; object-src 'none'")
s = s.replace('<!-- @page -->', '<meta http-equiv="Content-Security-Policy" content="' + csp + '">\n<!-- @page -->', 1)
open(p, 'w', encoding='utf-8').write(s)
PY
printf '{"build": %d}\n' "$WEB_BUILD" > "$OUT_DIR/bundle.json"
