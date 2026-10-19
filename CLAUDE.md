# CLAUDE.md

이 저장소에는 두 프로젝트가 있다.
- `app.py` — Streamlit 투자 상담 챗봇 (별개, 건드리지 않음)
- `booking_agent/` — 예약/티켓팅 취소표 모니터링 에이전트. 설계·규칙은 `booking_agent/PLAN.md`

사용자는 비개발자에 가깝다. 한국어로, 짧게, 다음에 무엇을 해야 하는지 분명히 말한다.
사용자 손이 꼭 필요한 단계(카카오 로그인·동의, 키 복사)만 요청하고 나머지는 직접 실행한다.

## 사용자가 "실행"이라고 하면 — 런북

아래를 순서대로 진행한다. 이미 끝난 단계는 확인만 하고 넘어간다. 작업 디렉터리는 `booking_agent/`.

### 0. 환경 확인
- `uname` 이 `Darwin` 이어야 한다(맥북). 클라우드 세션이면 "맥북에서 실행해야 합니다"라고 알리고 멈춘다.
- 저장소가 `~/Desktop`, `~/Documents`, `~/Downloads` 아래면 launchd 권한 문제가 생길 수 있다. 사용자에게 `~/chatbot` 으로 옮길지 묻는다.
- `git pull origin ccr-32847251-ycay6q` 로 최신화한다.

### 1. 설치
`bash scripts/setup.sh` — venv, 의존성, Chromium, 테스트까지 한 번에 진행한다. 실패하면 메시지대로 해결한다(Xcode CLT, Python 버전 등).

### 2. NOL 화담숲 어댑터 완성 (`agent/adapters/nol.py` 의 `_parse` 가 NotImplementedError 면)
클라우드 개발 환경에서는 NOL 접속이 막혀 있어서 이 부분이 비어 있다. 맥북에서 직접 완성한다.
1. `.venv/bin/python tools/discover.py --auto` 실행 → `captures/` 에 JSON 응답·HTML·스크린샷이 저장된다.
2. 스크린샷과 JSON을 읽고 다음을 찾는다: 날짜별 입장 회차(정각/20분/40분), 회차별 잔여 수량 또는 매진 여부, 1인 가격, 취소/환불 규정 문구.
   자동 클릭으로 부족하면 Playwright 스크립트를 직접 작성해서 탐색한다(scratch 파일, 커밋하지 않음).
3. `NolAdapter.fetch_slots` / `_parse` 를 구현한다. 다음 계약을 지킨다.
   - 대상 날짜(`watch.dates`)의 **모든 회차**를 반환한다(매진 포함, `available=False`). 0개를 반환하면 runner가 파싱 실패로 보고 경고한다.
   - 날짜를 클릭해야 회차 API가 호출되는 구조면 fetch_slots 안에서 날짜를 클릭한다. 공개 JSON API가 있으면 API 호출이 더 낫다.
   - 다음 달(11/1) 이동이 필요하면 처리한다.
4. 수집한 응답 중 필요한 부분만 `tests/fixtures/nol/` 에 저장하고 `tests/test_nol_parse.py` 로 파싱 테스트를 추가한다.
   **개인정보·쿠키·토큰이 없는지 확인한 뒤에만** 저장한다. `captures/` 는 커밋하지 않는다(gitignore).
5. `.venv/bin/python -m agent.runner --probe` 로 실제 회차가 맞게 나오는지 확인한다. ★=기준 충족, ○=예약 가능(기준 밖), ×=매진.
   스크린샷 속 화면과 결과가 일치하는지 대조한다.
6. 페이지의 취소 규정을 `watches.yaml` 의 `cancel_policy.tiers` 에 반영한다(형식은 파일 주석 참고). 원문을 사용자에게 한 줄로 보여준다.
7. `.venv/bin/python -m pytest -q` 를 통과시킨 뒤 커밋하고 `git push -u origin ccr-32847251-ycay6q` 한다.

금지: CAPTCHA 풀이, 봇 탐지 회피(stealth 플러그인, 핑거프린트 위장, 프록시 로테이션), 대기열 우회, 자동 로그인.
차단이나 CAPTCHA가 나오면 멈추고 사용자에게 상황을 보고한다. 폴링 간격은 60초 미만으로 줄이지 않는다.

### 3. 알림 연결
- 맥 알림(`mac`)은 설정 없이 바로 동작한다. **카카오가 아직이어도 감시를 먼저 시작**하고(4단계), 카카오는 그다음에 붙인다.
- 카카오(`~/.booking_agent/kakao_token.json` 이 없으면):
  1. `open https://developers.kakao.com/console/app` 으로 브라우저를 열고 사용자에게 안내한다.
     앱 추가 → [앱 키] REST API 키 복사 → [카카오 로그인] 활성화 ON, Redirect URI `http://localhost:8765/callback`
     → [동의항목] 카카오톡 메시지 전송 사용 → [플랫폼] Web 도메인 `https://leisure-web.yanolja.com`, `https://nol.yanolja.com`
     (메뉴 이름은 바뀌었을 수 있으니 화면을 보고 안내한다.)
  2. 사용자가 REST API 키를 주면 `booking_agent/.env` 의 `KAKAO_REST_API_KEY=` 에 넣는다(권한 600 유지, 커밋 금지).
  3. `.venv/bin/python tools/kakao_auth.py` → 사용자가 브라우저에서 동의 → 카톡 "나와의 채팅"에 테스트 메시지가 오는지 확인한다.
  4. `bash scripts/service.sh restart`
- `.venv/bin/python -m agent.runner --test-notify` 로 모든 채널을 테스트한다.

### 4. 감시 시작
1. `bash scripts/service.sh install` — launchd 백그라운드 서비스로 등록한다. 터미널이나 Claude를 닫아도 계속 돌고, 재부팅·로그인 시 자동으로 시작된다.
2. 2~3분 뒤 `bash scripts/service.sh status` 로 `poll` 이 돌고 오류가 없는지 확인한다.
   `sqlite3 ~/.booking_agent/agent.db "select * from events order by at desc limit 10"` 도 함께 본다.
3. 사용자에게 보고한다: 감시 대상, 확인 주기, 알림 채널, 그리고 **맥북은 전원을 연결하고 덮개를 연 채로 둘 것**.

## 그 외 명령
| 사용자가 말하면 | 할 일 |
|---|---|
| 상태 / 잘 돌아가? | `bash scripts/service.sh status` + 최근 events 요약 |
| 예약했어 / 그만 | `.venv/bin/python -m agent.runner --mark-booked <watch id>` 후 `bash scripts/service.sh stop` |
| 중지 | `bash scripts/service.sh stop` |
| 날짜·시간·인원 바꿔줘 | `watches.yaml` 수정 → `--probe` 로 확인 → `bash scripts/service.sh restart` |
| 새 대상 추가 | PLAN.md §9.3 온보딩: `--check-url URL`로 robots 판정 → 약관 확인 후 `watches.yaml`의 `sites`에 판정 기록(명시적 금지면 중단) → http_json·html 규칙 작성 → `--probe`로 화면과 대조. 후보 목록은 `research/platform_survey.csv`의 `새 규칙 판정`. 기본값은 `notify_only` |

## 변경 금지 규칙 (PLAN.md 원칙)
- 결재 게이트(10만원 이상 / 예약 시점 취소수수료 10% 초과 / 수수료 10% 이하 취소 가능 기간 24시간 미만 / 금액·규정 불명 → 승인 필요)를 완화하지 않는다.
- 확정 직전 재검증, `dry_run` 기본값, 일일 한도, KILL 파일 동작을 유지한다.
- NOL은 `notify_only`. 결제는 사용자가 직접 한다.
- 코드를 수정하면 `pytest` 통과 후 커밋·푸시한다.
