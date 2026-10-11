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
│   ├── java/com/geuhaeyeoreum/camera/MainActivity.java   ← WebView 셸 전체 (AndroidX 없이 프레임워크 API만)
│   └── res/                                               ← 앱 이름, 테마, 아이콘(적응형 포함)
├── tools/
│   ├── Sign.java        ← apksig로 v2 서명 + 검증
│   └── zipalign.py      ← 압축 안 된 항목 4바이트 정렬
└── build-apk.sh         ← SDK 없이 APK 빌드
```

`MainActivity`가 하는 일은 다음과 같습니다.

- **보안 출처로 제공:** `https://appassets.androidplatform.net/assets/…` 요청을 가로채 APK 안의 `assets/www/`를 보여 줍니다. 덕분에 페이지가 보안 컨텍스트가 되어 카메라, IndexedDB, localStorage가 정상 동작합니다. 그 밖의 외부 http(s) 요청은 막습니다.
- **카메라:** `getUserMedia` 요청이 오면 런타임 CAMERA 권한을 받은 뒤 허용합니다.
- **갤러리 저장:** `GeuhaeNative.saveImage()`가 MediaStore의 `Pictures/그해여름`에 저장합니다. Android 10 이상은 권한 없이 저장합니다. 9 이하는 저장공간 권한을 한 번 묻고, 답을 기다리는 동안 찍은 사진은 허용되면 한꺼번에 저장합니다.
- **카메라 권한:** 대화상자를 그냥 닫은 경우와 '다시 묻지 않음'을 구분합니다. 앞의 경우는 다시 묻고, 뒤의 경우에만 '설정 열기'를 안내합니다.
- **사진 고르기:** Android 13 이상은 시스템 사진 선택기, 그 아래 버전은 문서 선택기를 씁니다.
- **뒤로가기:** 페이지에 먼저 물어봅니다(`geuhaeOnBack`). 열린 창이 있으면 그것만 닫습니다. 첫 화면에서 누르면 앱을 끝내지 않고 홈 버튼처럼 뒤로 보냅니다. 그래서 현상 중인 사진이 사라지지 않습니다.
- **생명주기:** 백그라운드로 가면 카메라를 끄고, 돌아오면 다시 켭니다. WebView 렌더러가 죽으면 화면을 다시 만듭니다.
- **기타:** 볼륨키 셔터, 햅틱(시스템 햅틱 설정을 따름), 카메라 바디 색에 맞춘 상태바·내비게이션바 색, 화면 켜짐 유지.

## 빌드

### Android Studio 없이 (이 저장소의 기본 방법)

```bash
./android/build-apk.sh
# → android/build/geuhae-yeoreum-1.2.0.apk
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
| `VERSION_CODE` / `VERSION_NAME` | `3` / `1.2.0` |
| `KEYSTORE` / `STOREPASS` / `KEY_ALIAS` | `keystore/sideload.p12` / `geuhae-sideload` / `geuhae` |
| `TOOLS_DIR` | `android/.tools` |

### 서명 키 — 꼭 보관하세요

- 키 파일이 없으면 빌드 스크립트가 `keystore/sideload.p12`를 새로 만듭니다.
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
