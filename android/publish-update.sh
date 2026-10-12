#!/usr/bin/env bash
# Publishes the current ../retro-camera page as a web update for installed apps (1.3.0 and later).
# Writes android/update/: the page files, manifest.json and manifest.sig (signed with the APK key).
# Commit and push android/update/ afterwards; apps pick it up the next time they are opened.
#
# Apps look on two channels, main and claude/retro-camera-app-design-67gfwt, and take the highest build
# from either, so publish from one of those branches.
#
#   ./android/publish-update.sh                 # next build number, same shell requirement as before
#   NOTES="…" ./android/publish-update.sh
#   APK=android/build/geuhae-yeoreum-1.4.0.apk MIN_NATIVE=6 ./android/publish-update.sh
#       (an update that needs a newer shell: older apps are pointed at this APK instead)
#
# Build numbers: an APK with VERSION_CODE n bundles web build n*100, so updates on top of it are n*100+1, +2, …
# Set UPDATE_DIR to publish somewhere else for testing (skips the branch checks).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${UPDATE_DIR:-$HERE/update}"
KEYSTORE="${KEYSTORE:-$HERE/keystore/sideload.p12}"
STOREPASS="${STOREPASS:-geuhae-sideload}"
ALIAS="${KEY_ALIAS:-geuhae}"
PKG="com.geuhaeyeoreum.camera"
CHANNELS="main claude/retro-camera-app-design-67gfwt"   # must match UPDATE_BRANCHES in MainActivity
APP_NAME="$(sed -n 's/^VERSION_NAME="\${VERSION_NAME:-\(.*\)}"$/\1/p' "$HERE/build-apk.sh")"
APP_CODE="$(sed -n 's/^VERSION_CODE="\${VERSION_CODE:-\(.*\)}"$/\1/p' "$HERE/build-apk.sh")"
[ -n "$APP_NAME" ] && [ -n "$APP_CODE" ] || { echo "could not read VERSION_NAME / VERSION_CODE from build-apk.sh" >&2; exit 1; }

if [ ! -f "$KEYSTORE" ] && [ -n "${GEUHAE_KEYSTORE_B64:-}" ]; then
  mkdir -p "$(dirname "$KEYSTORE")" && printf '%s' "$GEUHAE_KEYSTORE_B64" | base64 -d > "$KEYSTORE"
fi
[ -f "$KEYSTORE" ] || { echo "signing key not found: $KEYSTORE (the same key that signs the APK; or set GEUHAE_KEYSTORE_B64)" >&2; exit 1; }
mkdir -p "$DEST"
if [ -n "$(ls -A "$DEST")" ] && [ ! -f "$DEST/manifest.json" ]; then
  echo "$DEST has files but no manifest.json; not overwriting it" >&2; exit 1
fi

# The newest manifest anywhere apps look: here and on every channel.
MANIFESTS=()
[ -f "$DEST/manifest.json" ] && MANIFESTS+=("$DEST/manifest.json")
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
if [ -z "${UPDATE_DIR:-}" ]; then
  BRANCH="$(git -C "$HERE" rev-parse --abbrev-ref HEAD)"
  case " $CHANNELS " in *" $BRANCH "*) ;; *)
    echo "on branch $BRANCH, which apps do not read. Publish from one of: $CHANNELS" >&2; exit 1 ;;
  esac
  for b in $CHANNELS; do
    git -C "$HERE" fetch -q origin "$b" 2>/dev/null || echo "  (could not fetch $b; using what is known locally)" >&2
    if git -C "$HERE" show "origin/$b:android/update/manifest.json" > "$TMP/$(echo "$b" | tr / _).json" 2>/dev/null; then
      MANIFESTS+=("$TMP/$(echo "$b" | tr / _).json")
    fi
  done
fi
read -r PREV PREV_MIN PREV_APK < <(python3 - "${MANIFESTS[@]+"${MANIFESTS[@]}"}" <<'PY'
import json, sys
best = {"build": 0, "minNative": 0, "apk": "-"}
for p in sys.argv[1:]:
    try:
        m = json.load(open(p, encoding="utf-8"))
    except Exception:
        continue
    if int(m.get("build", 0)) > best["build"]:
        best = {"build": int(m.get("build", 0)), "minNative": int(m.get("minNative", 0)), "apk": m.get("apk") or "-"}
print(best["build"], best["minNative"], best["apk"])
PY
)

FLOOR=$((APP_CODE * 100))
# Never quietly lower the shell requirement of what is already out; MIN_NATIVE=… lowers it on purpose.
MIN_NATIVE="${MIN_NATIVE:-$(( PREV_MIN > 5 ? PREV_MIN : 5 ))}"
BUILD="${BUILD:-$(( (PREV > FLOOR ? PREV : FLOOR) + 1 ))}"
[ "$BUILD" -gt "$PREV" ] || { echo "BUILD $BUILD must be greater than the published $PREV" >&2; exit 1; }
[ "$BUILD" -ge "$FLOOR" ] || { echo "BUILD $BUILD is older than what app $APP_NAME bundles ($FLOOR)" >&2; exit 1; }
if [ "$BUILD" -gt "$FLOOR" ]; then LABEL="${LABEL:-$APP_NAME+$((BUILD - FLOOR))}"; else LABEL="${LABEL:-$APP_NAME}"; fi

"$HERE/tools/web-assets.sh" "$TMP/www" "$BUILD"
rm "$TMP/www/bundle.json"
# Start clean so files dropped from the page do not linger; keep the APK that older apps may still be sent to.
find "$DEST" -mindepth 1 -maxdepth 1 ! -name geuhae-yeoreum.apk -exec rm -rf {} +
cp -R "$TMP/www/." "$DEST/"
APK_NAME=""
if [ -n "${APK:-}" ]; then
  APK_NAME="geuhae-yeoreum.apk"
  cp "$APK" "$DEST/$APK_NAME"
elif [ "$PREV_APK" != "-" ] && [ -f "$DEST/$PREV_APK" ]; then
  APK_NAME="$PREV_APK"   # still the APK for apps older than MIN_NATIVE
else
  rm -f "$DEST/geuhae-yeoreum.apk"
fi

python3 - "$DEST" "$PKG" "$BUILD" "$LABEL" "$MIN_NATIVE" "$APK_NAME" "${NOTES:-}" <<'PY'
import hashlib, json, os, re, sys, datetime
dest, pkg, build, label, min_native, apk, notes = sys.argv[1:8]
safe = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}(/[A-Za-z0-9][A-Za-z0-9._-]{0,63}){0,3}\Z")  # UpdateBundle.SAFE
files = {}
for d, _, names in os.walk(dest):
    for n in names:
        rel = os.path.relpath(os.path.join(d, n), dest).replace(os.sep, "/")
        if rel in ("manifest.json", "manifest.sig", apk) or (not apk and rel == "geuhae-yeoreum.apk"):
            continue
        if not safe.match(rel):
            sys.exit(f"file name the app would refuse: {rel}")
        data = open(os.path.join(dest, rel), "rb").read()
        if len(data) > 8 * 1024 * 1024:
            sys.exit(f"{rel} is over the app's 8 MB limit per file")
        files[rel] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
m = {"package": pkg, "build": int(build), "version": label, "minNative": int(min_native),
     "files": dict(sorted(files.items())),
     "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}
if apk:
    m["apk"] = apk
if notes:
    m["notes"] = notes
open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8").write(json.dumps(m, ensure_ascii=False, indent=1) + "\n")
PY
java "$HERE/tools/SignUpdate.java" "$KEYSTORE" "$STOREPASS" "$ALIAS" "$DEST/manifest.json" "$DEST/manifest.sig"
echo "▸ web update $LABEL (build $BUILD, needs app code ≥ $MIN_NATIVE${APK_NAME:+, older apps get $APK_NAME}) in $DEST"
[ -n "${UPDATE_DIR:-}" ] || echo "  commit and push android/update/ on $BRANCH to publish it"
