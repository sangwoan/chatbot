# 예약 모니터링 에이전트

취소표를 감시하다가 기준(날짜·시간·인원·금액)에 맞는 자리가 나면 알림을 보낸다.
자동예약을 허용하는 플랫폼에서는 결재 게이트(10만원 / 취소수수료 10% / 남은 취소기간 1일)를 통과할 때만 확정한다.
설계와 규칙은 [PLAN.md](PLAN.md) 참고.

## 맥북 설치 (최초 1회)

```bash
git clone -b ccr-32847251-ycay6q https://github.com/sangwoan/chatbot.git
cd chatbot/booking_agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
python -m pytest -q              # 테스트 통과 확인
```

## 1단계 — NOL 페이지 구조 수집 (지금 필요)

```bash
python tools/discover.py
```
1. 열린 브라우저에서 **로그인하지 말고** 10/24 날짜를 클릭
2. 입장 시간 목록이 보이면 터미널에서 Enter
3. 10/25도 같은 방법으로 진행한 뒤 Enter, 끝나면 `q` 입력
4. 만들어진 `captures/` 폴더를 zip으로 보내기 (요청 헤더·쿠키는 저장되지 않음)

로그인해야 시간 목록이 보이면 그 상태로 진행하되, 보내기 전에 알려주세요.

## 2단계 — 카카오톡 알림 연결

1. https://developers.kakao.com → 내 애플리케이션 → 앱 추가
2. 앱 키에서 **REST API 키** 복사
3. 카카오 로그인 → 활성화 ON, Redirect URI에 `http://localhost:8765/callback` 등록
4. 동의항목 → **카카오톡 메시지 전송** 사용 설정
5. 플랫폼 → Web 사이트 도메인에 `https://leisure-web.yanolja.com` 와 `https://nol.yanolja.com` 등록 (등록하지 않으면 메시지 안 링크가 열리지 않음)
6. 실행:
   ```bash
   export KAKAO_REST_API_KEY=발급받은키
   python tools/kakao_auth.py        # 카톡 '나와의 채팅'에 테스트 메시지가 오면 성공
   ```
   토큰은 `~/.booking_agent/kakao_token.json`에 저장되고 자동 갱신된다.
   refresh token은 최대 2개월 유효하며, 만료 1개월 이내에 갱신되면 새 토큰이 발급된다.

## 3단계 — 실행

```bash
export KAKAO_REST_API_KEY=발급받은키
python -m agent.runner --test-notify                        # 알림 테스트
caffeinate -i python -m agent.runner -c watches.yaml        # 상시 감시 (잠자기 방지)
```
- 맥북은 **전원 연결 + 덮개 열림** 상태로 두기 (덮개를 닫으면 잠자기에 들어가 감시가 멈춤)
- 3회 연속 실패하면(로그인 만료, 페이지 구조 변경 등) 경고 알림이 온다
- 자동결제 긴급 중지: `touch ~/.booking_agent/KILL` (알림 전용으로 전환)
- 기록: `~/.booking_agent/agent.db` (SQLite)

## 설정 (`watches.yaml`)
- `dates`: 앞에 있을수록 우선
- `cancel_policy.tiers`: 비워두면 '모름'으로 처리 → 자동 확정 금지
- `dry_run: true` 기본값. 실제 자동결제는 대상별로 확인한 뒤에만 끈다
