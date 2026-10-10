#!/usr/bin/env bash
# Builds an installable, signed 그해여름 APK without Android Studio or the Android SDK.
# Needs: bash, curl, python3, zip, JDK 17+ (javac/java/keytool).
# Tools are downloaded once into $TOOLS_DIR and checked against pinned SHA-256 sums:
#   aapt2 2.20     npm aaptjs3@2.0.2 (prebuilt linux binary)
#   android.jar    API 35 stubs from github.com/Sable/android-platforms
#   D8 8.5.35      r8lib.jar from storage.googleapis.com/r8-releases
#   apksig 2.3.0   Maven Central (APK Signature Scheme v2; minSdk 24 needs no v1)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
WEB="$HERE/../retro-camera"
SRC="$HERE/app/src/main"
OUT="$HERE/build"
TOOLS="${TOOLS_DIR:-$HERE/.tools}"
MIN_SDK=24
TARGET_SDK=35
VERSION_CODE="${VERSION_CODE:-2}"
VERSION_NAME="${VERSION_NAME:-1.1.0}"
KEYSTORE="${KEYSTORE:-$HERE/keystore/sideload.p12}"
STOREPASS="${STOREPASS:-geuhae-sideload}"
ALIAS="${KEY_ALIAS:-geuhae}"
APK_NAME="geuhae-yeoreum-$VERSION_NAME.apk"

fetch() { # url sha256 dest
  local url="$1" sum="$2" dest="$3"
  if [ -f "$dest" ] && echo "$sum  $dest" | sha256sum -c --quiet - 2>/dev/null; then return; fi
  mkdir -p "$(dirname "$dest")"
  for i in 1 2 3 4 5; do
    if curl -fsSL --max-time 300 -o "$dest.part" "$url"; then break; fi
    echo "  retry $i: $url" >&2; sleep $((i * 8))
  done
  echo "$sum  $dest.part" | sha256sum -c --quiet -
  mv "$dest.part" "$dest"
}

echo "▸ tools"
fetch https://registry.npmjs.org/aaptjs3/-/aaptjs3-2.0.2.tgz \
  26031bd1acb577edce91675ae92daf63cf85795d4e2399333edeb994dd9197e9 "$TOOLS/aaptjs3-2.0.2.tgz"
fetch https://raw.githubusercontent.com/Sable/android-platforms/master/android-35/android.jar \
  4566663c3876e022b4fa4ced8c8697c4ab1688267f090114fd92d027b32e619b "$TOOLS/android-35.jar"
fetch https://storage.googleapis.com/r8-releases/raw/8.5.35/r8lib.jar \
  4733945987ee0a840fafc34080b135259e01678412e07212b23f706334290294 "$TOOLS/r8lib-8.5.35.jar"
fetch https://repo.maven.apache.org/maven2/com/android/tools/build/apksig/2.3.0/apksig-2.3.0.jar \
  9637078c0016244e4be0941836295365a7e2e5b164c59cb7885783c40460bfee "$TOOLS/apksig-2.3.0.jar"
AAPT2="$TOOLS/aapt2"
if [ ! -x "$AAPT2" ]; then
  tar -xzf "$TOOLS/aaptjs3-2.0.2.tgz" -C "$TOOLS" package/bin/x64/linux/aapt2
  mv "$TOOLS/package/bin/x64/linux/aapt2" "$AAPT2" && rm -rf "$TOOLS/package" && chmod +x "$AAPT2"
fi
ANDROID_JAR="$TOOLS/android-35.jar"

if [ ! -f "$KEYSTORE" ]; then
  echo "▸ new signing key: $KEYSTORE"
  mkdir -p "$(dirname "$KEYSTORE")"
  keytool -genkeypair -keystore "$KEYSTORE" -storetype PKCS12 -storepass "$STOREPASS" -alias "$ALIAS" \
    -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Geuhae Yeoreum, O=Sideload, C=KR" 2>/dev/null
fi

rm -rf "$OUT"
mkdir -p "$OUT/assets/www" "$OUT/classes" "$OUT/dex" "$OUT/signer"

echo "▸ web assets"
cp "$WEB/index.html" "$WEB/icon.svg" "$OUT/assets/www/"
cp -R "$WEB/fonts" "$OUT/assets/www/fonts"
# The APK is offline-first: drop the Google Fonts stylesheet, the bundled fonts/fonts.css covers it.
python3 - "$OUT/assets/www/index.html" <<'PY'
import re, sys
p = sys.argv[1]
s = open(p, encoding='utf-8').read()
s = re.sub(r'\n?<link[^>]+fonts\.(googleapis|gstatic)\.com[^>]*>', '', s)
# Nothing in the APK talks to the network: lock the page to its own origin.
csp = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' blob: data:; media-src 'self' blob: mediastream:; font-src 'self' data:; "
       "connect-src 'self' blob: data:; worker-src 'none'; frame-src 'none'; object-src 'none'")
s = s.replace('<!-- @page -->', '<meta http-equiv="Content-Security-Policy" content="' + csp + '">\n<!-- @page -->', 1)
open(p, 'w', encoding='utf-8').write(s)
PY

echo "▸ resources (aapt2)"
"$AAPT2" compile --dir "$SRC/res" -o "$OUT/res.zip"
"$AAPT2" link -o "$OUT/base.apk" -I "$ANDROID_JAR" \
  --manifest "$SRC/AndroidManifest.xml" -A "$OUT/assets" \
  --min-sdk-version "$MIN_SDK" --target-sdk-version "$TARGET_SDK" \
  --version-code "$VERSION_CODE" --version-name "$VERSION_NAME" \
  -0 woff2 -0 png -0 jpg \
  "$OUT/res.zip"

echo "▸ code (javac + d8)"
javac -source 8 -target 8 -bootclasspath "$ANDROID_JAR" -encoding UTF-8 -Xlint:-options -nowarn \
  -d "$OUT/classes" $(find "$SRC/java" -name '*.java')
java -cp "$TOOLS/r8lib-8.5.35.jar" com.android.tools.r8.D8 --release --min-api "$MIN_SDK" \
  --lib "$ANDROID_JAR" --output "$OUT/dex" $(find "$OUT/classes" -name '*.class')

echo "▸ package, align, sign"
cp "$OUT/base.apk" "$OUT/unsigned.apk"
(cd "$OUT/dex" && zip -q -X "$OUT/unsigned.apk" classes.dex)
python3 "$HERE/tools/zipalign.py" "$OUT/unsigned.apk" "$OUT/aligned.apk"
javac -cp "$TOOLS/apksig-2.3.0.jar" -d "$OUT/signer" "$HERE/tools/Sign.java"
# apksig 2.3.0 builds v1 signatures with JDK-internal sun.security classes
java --add-exports java.base/sun.security.x509=ALL-UNNAMED --add-exports java.base/sun.security.pkcs=ALL-UNNAMED \
  --add-exports java.base/sun.security.util=ALL-UNNAMED -cp "$TOOLS/apksig-2.3.0.jar:$OUT/signer" Sign "$OUT/aligned.apk" "$OUT/$APK_NAME" \
  "$KEYSTORE" "$STOREPASS" "$ALIAS" "$MIN_SDK"
python3 "$HERE/tools/zipalign.py" --check "$OUT/$APK_NAME"

echo "▸ result"
"$AAPT2" dump badging "$OUT/$APK_NAME" | grep -E "^(package|sdkVersion|targetSdkVersion|application-label|uses-permission):" || true
ls -l "$OUT/$APK_NAME"
