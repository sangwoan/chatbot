# 그해여름 — Android 앱 (APK)

`../retro-camera`의 웹 카메라를 안드로이드 앱으로 감싼 프로젝트입니다. 화면과 촬영 로직은 웹 버전과 같은 `index.html`을 쓰고, 안드로이드 쪽은 웹만으로는 안 되는 부분만 맡습니다.

- 기기 카메라 권한
- 휴대폰 갤러리 저장
- 공유
- 사진 고르기
- 햅틱
- 볼륨키 셔터
- 상태바 색
- 뒤로가기

## 설치 (사이드로드)

1. `geuhae-yeoreum-<버전>.apk`를 휴대폰으로 옮깁니다(카톡 나에게 보내기, 드라이브, USB 등).
2. 파일을 누르면 "출처를 알 수 없는 앱 설치" 허용을 묻습니다. 그 앱(파일 관리자, 브라우저 등)에 허용합니다.
3. Play 프로텍트가 "알 수 없는 개발자" 경고를 띄우면 **무시하고 설치**를 누릅니다. 스토어에 올리지 않은 개인 앱이라 생기는 경고입니다.

필요 사양: Android 7.0(API 24) 이상, 카메라, 최신 Android System WebView.

## 앱이 쓰는 권한

| 권한 | 쓰는 곳 |
|---|---|
| 카메라 | 실시간 뷰파인더 (처음 켤 때 물어봄) |
| 저장공간 (Android 9 이하만) | 갤러리 저장. Android 10 이상은 권한 없이 `사진/그해여름` 앨범에 저장 |
| 진동 | 셔터·다이얼 햅틱 |
| 인터넷 | WebView 동작용으로만 선언. 앱 파일은 모두 APK 안에서 읽고, 외부 주소 요청은 앱이 막습니다 |

위치 권한은 쓰지 않습니다. 위치(좌표) 스탬프는 웹 버전에만 있습니다. 출처를 알 수 없는 앱이 카메라·위치·인터넷 권한을 함께 가지면 보안 앱이 스파이앱 패턴으로 보기 쉽습니다. 그래서 위험 권한은 카메라 하나만 남겼습니다.

## 구조

```
android/
├── app/src/main/
│   ├── AndroidManifest.xml
│   ├── java/com/geuhaeyeoreum/camera/
│   │   ├── MainActivity.java   ← WebView 셸 전체 (AndroidX 없이 프레임워크 API만)
│   │   ├── Updater.java        ← 웹 업데이트 확인·내려받기·적용·되돌리기
│   │   └── UpdateBundle.java   ← 업데이트 목록(manifest) 서명 검증
│   └── res/                    ← 앱 이름, 테마, 아이콘(적응형 포함)
├── tools/
│   ├── Sign.java        ← apksig로 v2 서명 + 검증
│   ├── SignUpdate.java  ← 웹 업데이트 목록 서명 (APK와 같은 키)
│   ├── web-assets.sh    ← APK와 업데이트가 함께 쓰는 웹 파일 준비 (CSP, 빌드 번호)
│   └── zipalign.py      ← 압축 안 된 항목 4바이트 정렬
├── update/              ← 공개된 웹 업데이트 (앱이 여기서 받아 감)
├── build-apk.sh         ← SDK 없이 APK 빌드
└── publish-update.sh    ← 웹 업데이트 서명해서 update/에 쓰기
```

`MainActivity`가 하는 일은 다음과 같습니다.

- **보안 출처로 제공:** `https://appassets.androidplatform.net/assets/…` 요청을 가로채 APK 안의 `assets/www/`를 보여 줍니다. 덕분에 페이지가 보안 컨텍스트가 되어 카메라, IndexedDB, localStorage가 정상 동작합니다. 그 밖의 외부 http(s) 요청은 막습니다.
- **카메라:** `getUserMedia` 요청이 오면 런타임 CAMERA 권한을 받은 뒤 허용합니다.
- **갤러리 저장:** `GeuhaeNative.saveImage()`가 MediaStore의 `Pictures/그해여름`에 저장합니다. Android 10 이상은 권한 없이 저장합니다. 9 이하는 저장공간 권한을 한 번 묻고, 답을 기다리는 동안 찍은 사진은 허용되면 한꺼번에 저장합니다.
- **카메라 권한:** 대화상자를 그냥 닫은 경우와 '다시 묻지 않음'을 구분합니다. 앞의 경우는 다시 묻고, 뒤의 경우에만 '설정 열기'를 안내합니다.
- **사진 고르기:** Android 13 이상은 시스템 사진 선택기, 그 아래 버전은 문서 선택기를 씁니다.
- **뒤로가기:** 페이지에 먼저 물어봅니다(`geuhaeOnBack`). 열린 창이 있으면 그것만 닫습니다. 첫 화면에서 누르면 앱을 끝내지 않고 홈 버튼처럼 뒤로 보냅니다. 그래서 현상 중인 사진이 사라지지 않습니다.
- **생명주기:** 백그라운드로 가면 카메라를 끄고, 돌아오면 다시 켭니다. WebView 렌더러가 죽으면 화면을 다시 만듭니다.
- **자동 업데이트:** 아래 '자동 업데이트' 참고. 업데이트된 파일이 있으면 그 파일을, 없으면 APK 안의 파일을 보여 줍니다.
- **기타:** 볼륨키 셔터, 햅틱(시스템 햅틱 설정을 따름), 카메라 바디 색에 맞춘 상태바·내비게이션바 색, 화면 켜짐 유지.

## 자동 업데이트 (1.3.0부터)

1.3.0부터는 화면, 카메라, 필터 같은 웹 부분을 앱이 스스로 업데이트합니다. APK를 다시 받을 필요가 없습니다.

1. 앱을 열 때마다(그리고 15분 넘게 나갔다 돌아올 때마다) 아래 주소에서 `manifest.json`과 `manifest.sig`를 확인합니다.
   - `https://raw.githubusercontent.com/sangwoan/chatbot/main/android/update/`
   - `https://raw.githubusercontent.com/sangwoan/chatbot/claude/retro-camera-app-design-67gfwt/android/update/`

   두 곳 중 빌드 번호가 높은 쪽을 씁니다.
2. 다음을 모두 통과해야 받아들입니다.
   - `manifest.sig`가 **APK를 서명한 바로 그 키로 만든 서명**이어야 합니다(SHA256withRSA). 앱은 자기 서명 인증서의 공개 키로 확인합니다.
   - 패키지 이름이 일치해야 합니다.
   - 빌드 번호가 지금 것보다 커야 합니다.
   - 파일마다 크기와 SHA-256이 맞아야 합니다.
3. 받은 파일은 앱 전용 저장소(`files/ota`)에 둡니다.
   - 촬영·현상 중이 아니고 창이 열려 있지 않으면 바로 적용하고 화면을 다시 불러옵니다.
   - 바쁘면 끝나는 즉시 적용합니다.
   - 페이지 주소(출처)는 그대로라서 앱 안 앨범과 설정이 유지됩니다.
4. 새 화면이 12초 안에 정상 시작 신호(`bootOk`)를 보내지 않으면 그 업데이트를 버리고 APK 안의 화면으로 되돌아갑니다. 같은 빌드는 다시 받지 않습니다.
5. 안드로이드 코드가 바뀌어야 하는 업데이트(`minNative`가 앱 버전 코드보다 큼)는 받지 않습니다. 메뉴 › 앱에 '받기' 버튼을 띄워 새 APK를 내려받게 합니다.

권한은 늘지 않습니다(카메라·인터넷·진동·Android 9 이하 저장공간). 다른 앱을 설치하는 권한(`REQUEST_INSTALL_PACKAGES`)은 쓰지 않습니다.

### 업데이트 올리기

```bash
./android/publish-update.sh            # retro-camera/index.html을 다음 빌드 번호로 서명해 android/update/에 씀
git add android/update && git commit -m "web update" && git push
```

- 빌드 번호 규칙: APK에 들어 있는 웹 빌드는 `버전코드 × 100`입니다(1.3.0 = 500). 웹 업데이트는 그보다 커야 합니다(501, 502…).
- 안드로이드 코드도 바꿨다면 다음처럼 올립니다. 그러면 예전 앱은 웹 업데이트 대신 APK 받기 안내를 보여 줍니다.
  1. `VERSION_CODE`를 올려 APK를 빌드합니다.
  2. `APK=android/build/…apk MIN_NATIVE=<새 버전코드> ./android/publish-update.sh`를 실행합니다.

### 서명 키가 꼭 필요합니다

APK 서명과 업데이트 서명이 같은 키(`keystore/sideload.p12`)입니다. 키가 없으면 두 가지가 모두 불가능합니다.
- 설치된 앱 위에 덮어 설치하기
- 설치된 앱이 받아들이는 업데이트 만들기

그래서 `build-apk.sh`는 키가 없으면 멈춥니다. 새 키로 처음부터 다시 시작하려면 `NEW_KEY=1`을 붙여 실행합니다.

새 작업 환경에서 키를 쓰는 방법은 두 가지입니다.
- 파일을 `android/keystore/sideload.p12`에 둡니다.
- 환경 변수 `GEUHAE_KEYSTORE_B64`에 p12 파일의 base64를 넣습니다. 스크립트가 알아서 복원합니다.

키 파일은 공개 저장소에 올리지 않습니다(`.gitignore`). 키가 새면 남이 이 앱의 업데이트를 만들 수 있으니 따로 안전하게 보관하세요.

## 빌드

### Android Studio 없이 (이 저장소의 기본 방법)

```bash
./android/build-apk.sh
# → android/build/geuhae-yeoreum-1.3.0.apk
```

필요한 것은 bash, curl, python3, zip, JDK 17 이상(`javac`, `java`, `keytool`)뿐입니다. 빌드 도구는 처음 한 번 내려받고 SHA-256으로 검증합니다.

| 도구 | 출처 |
|---|---|
| aapt2 2.20 | npm `aaptjs3@2.0.2` (프리빌트 리눅스 바이너리) |
| android.jar (API 35 스텁) | github.com/Sable/android-platforms |
| D8 8.5.35 | storage.googleapis.com/r8-releases |
| apksig 2.3.0 | Maven Central |

빌드 단계는 다음과 같습니다.
1. `../retro-camera`의 `index.html`, `icon.svg`, `fonts/`를 APK 안에 넣습니다. 이때 Google Fonts 링크를 빼고, 페이지를 자기 출처로만 묶는 CSP를 넣습니다.
2. aapt2로 리소스를 컴파일·링크합니다.
3. javac(`-source 8`)와 d8(`--min-api 24`)로 코드를 dex로 바꿉니다.
4. 압축 안 된 항목을 정렬합니다.
5. APK Signature Scheme v2로 서명하고 검증합니다.

v1 서명은 쓰지 않습니다. minSdk가 24라 v2만으로 충분하고, apksig 2.3.0의 v1 서명기는 최신 JDK에서 동작하지 않습니다.

환경 변수:

| 변수 | 기본값 |
|---|---|
| `VERSION_CODE` / `VERSION_NAME` | `5` / `1.3.0` |
| `WEB_BUILD` | `VERSION_CODE × 100` (APK에 들어가는 웹 빌드 번호) |
| `GEUHAE_KEYSTORE_B64` | 비어 있음. 서명 키 파일의 base64. 키 파일이 없을 때 복원합니다 |
| `NEW_KEY` | `0`. `1`이면 키가 없을 때 새로 만듭니다(기존 앱 위에 덮어 설치할 수 없게 됨) |
| `KEYSTORE` / `STOREPASS` / `KEY_ALIAS` | `keystore/sideload.p12` / `geuhae-sideload` / `geuhae` |
| `TOOLS_DIR` | `android/.tools` |

### 서명 키 — 꼭 보관하세요

- 키 파일이 없으면 빌드 스크립트는 멈춥니다. 처음부터 새 키로 시작할 때만 `NEW_KEY=1`로 `keystore/sideload.p12`를 새로 만듭니다.
- 같은 키로 웹 업데이트도 서명합니다(위 '자동 업데이트' 참고).
- **같은 키로 서명해야 설치된 앱 위에 업데이트할 수 있습니다.** 키가 바뀌면 기존 앱을 지우고 다시 설치해야 하고, 그러면 앱 안 앨범(IndexedDB)도 지워집니다. 휴대폰 갤러리에 저장된 사진은 남습니다.
- 이 저장소는 공개 저장소라 키 파일은 `.gitignore`로 커밋하지 않습니다. 따로 안전한 곳에 보관했다가, 다음 빌드 전에 `android/keystore/sideload.p12`에 다시 넣어 주세요.

## 검증한 것과 못 한 것

**검증한 것 (이 저장소의 빌드 환경)**
- 빌드 전 과정: 컴파일, dex, 리소스 링크, 정렬, 서명
- `ApkVerifier`의 v2 서명 검증
- 압축 안 된 항목 정렬, `aapt2 dump badging`
- APK에 들어가는 바로 그 `index.html`(CSP 적용본)을 Chromium에서 가짜 카메라로 돌린 촬영·현상·앨범·다시 현상·뒤로가기 시나리오

**못 한 것**
- 실제 기기나 에뮬레이터에서의 실행. 이 환경에서는 안드로이드 시스템 이미지를 받을 수 없습니다.

처음 설치한 뒤에는 다음을 한 번씩 확인해 주세요.
- 카메라 권한 → 실시간 화면
- 셔터 → 갤러리 `그해여름` 앨범에 저장되는지
- 볼륨키 셔터
- 앨범에서 가져오기
- 뒤로가기

## Android Studio로 열고 싶다면

Gradle 설정은 넣지 않았습니다. Android Studio에서 새 "Empty Views Activity" 프로젝트(패키지 `com.geuhaeyeoreum.camera`, minSdk 24)를 만든 뒤 다음처럼 옮기면 됩니다.
1. 위 `MainActivity.java`, `AndroidManifest.xml`, `res/`를 그대로 덮어씁니다.
2. `retro-camera/index.html`, `icon.svg`, `fonts/`를 `app/src/main/assets/www/`에 복사합니다. 이때 Google Fonts 링크 세 줄은 지웁니다.
