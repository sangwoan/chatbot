#!/usr/bin/env bash
# Publishes the current ../retro-camera page as a web update for installed apps (1.3.0 and later).
# Writes android/update/: index.html, icon.svg, manifest.json and manifest.sig (signed with the APK key).
# Commit and push android/update/ afterwards; apps pick it up the next time they are opened.
#
#   ./android/publish-update.sh                 # next build number, needs the shell from MIN_NATIVE on
#   NOTES="…" BUILD=503 ./android/publish-update.sh
#   APK=android/build/geuhae-yeoreum-1.4.0.apk MIN_NATIVE=6 ./android/publish-update.sh
#       (an update that needs a newer shell: older apps are pointed at this APK instead)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${UPDATE_DIR:-$HERE/update}"
KEYSTORE="${KEYSTORE:-$HERE/keystore/sideload.p12}"
STOREPASS="${STOREPASS:-geuhae-sideload}"
ALIAS="${KEY_ALIAS:-geuhae}"
PKG="com.geuhaeyeoreum.camera"
MIN_NATIVE="${MIN_NATIVE:-5}"   # the first app version with web updates (1.3.0)
APP_NAME="$(sed -n 's/^VERSION_NAME="\${VERSION_NAME:-\(.*\)}"$/\1/p' "$HERE/build-apk.sh")"

if [ ! -f "$KEYSTORE" ] && [ -n "${GEUHAE_KEYSTORE_B64:-}" ]; then
  mkdir -p "$(dirname "$KEYSTORE")" && printf '%s' "$GEUHAE_KEYSTORE_B64" | base64 -d > "$KEYSTORE"
fi
[ -f "$KEYSTORE" ] || { echo "signing key not found: $KEYSTORE (the same key that signs the APK; or set GEUHAE_KEYSTORE_B64)" >&2; exit 1; }
mkdir -p "$DEST"
PREV="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("build",0))' "$DEST/manifest.json" 2>/dev/null || echo 0)"
FLOOR=$((MIN_NATIVE * 100))
BUILD="${BUILD:-$(( (PREV > FLOOR ? PREV : FLOOR) + 1 ))}"
[ "$BUILD" -gt "$PREV" ] || { echo "BUILD $BUILD must be greater than the published $PREV" >&2; exit 1; }
LABEL="${LABEL:-$APP_NAME+$((BUILD - FLOOR))}"

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
"$HERE/tools/web-assets.sh" "$TMP" "$BUILD"
cp "$TMP/index.html" "$TMP/icon.svg" "$DEST/"
APK_NAME=""
if [ -n "${APK:-}" ]; then
  APK_NAME="geuhae-yeoreum.apk"
  cp "$APK" "$DEST/$APK_NAME"
fi

python3 - "$DEST" "$PKG" "$BUILD" "$LABEL" "$MIN_NATIVE" "$APK_NAME" "${NOTES:-}" <<'PY'
import hashlib, json, os, sys, datetime
dest, pkg, build, label, min_native, apk, notes = sys.argv[1:8]
files = {}
for name in ("index.html", "icon.svg"):
    data = open(os.path.join(dest, name), "rb").read()
    files[name] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
m = {"package": pkg, "build": int(build), "version": label, "minNative": int(min_native), "files": files,
     "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}
if apk:
    m["apk"] = apk
if notes:
    m["notes"] = notes
open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8").write(json.dumps(m, ensure_ascii=False, indent=1) + "\n")
PY
java "$HERE/tools/SignUpdate.java" "$KEYSTORE" "$STOREPASS" "$ALIAS" "$DEST/manifest.json" "$DEST/manifest.sig"
echo "▸ web update $LABEL (build $BUILD, needs app code ≥ $MIN_NATIVE) in $DEST"
echo "  commit and push android/update/ to publish it"
