# 예약 모니터링 에이전트

취소표를 감시하다가 기준(날짜·시간·인원·금액)에 맞는 자리가 나면 알림을 보낸다.
자동예약을 허용하는 플랫폼에서는 결재 게이트(10만원 / 취소수수료 10% / 남은 취소기간 1일)를 통과할 때만 확정한다.
설계와 규칙은 [PLAN.md](PLAN.md), Claude용 실행 순서는 [../CLAUDE.md](../CLAUDE.md) 참고.

## 맥북에서 시작하기 (사용자가 할 일)

**1. 터미널에서 한 번만:**
```bash
cd ~ && git clone -b ccr-32847251-ycay6q https://github.com/sangwoan/chatbot.git
```
Claude Code가 없다면 https://claude.com/claude-code 에서 설치한다.

**2. Claude를 이 폴더에서 연다** (둘 중 하나)
- Claude 데스크톱 앱 → Code → 폴더로 `~/chatbot` 선택
- 터미널: `cd ~/chatbot && claude` (휴대폰 앱에서도 보려면 `claude remote-control`)

**3. "실행"이라고 입력한다.** 나머지는 Claude가 진행한다. 중간에 카카오 로그인·동의와 키 복사만 요청한다.

## 직접 실행할 때 (참고)

```bash
cd ~/chatbot/booking_agent
bash scripts/setup.sh                          # 설치 + 테스트
.venv/bin/python tools/discover.py --auto      # NOL 페이지 구조 수집 → captures/
.venv/bin/python -m agent.runner --probe       # 현재 회차 출력 (★ 기준 충족 ○ 가능 × 매진)
.venv/bin/python tools/kakao_auth.py           # 카카오 연결 (.env에 REST 키 필요)
.venv/bin/python -m agent.runner --test-notify # 알림 테스트
bash scripts/service.sh install                # 백그라운드 감시 시작 (재부팅 후에도 자동)
bash scripts/service.sh status | logs | restart | stop
.venv/bin/python -m agent.runner --mark-booked hwadam-2026-fall   # 직접 예약 완료 → 감시 종료
```

- 맥북은 **전원 연결 + 덮개 열림** 상태로 둔다(덮개를 닫으면 잠자기에 들어가 감시가 멈춤). 실행 중에는 `caffeinate`가 잠자기를 막는다.
- 3회 연속 실패하면(페이지 구조 변경 등) 경고 알림이 온다.
- 자동결제 긴급 중지: `touch ~/.booking_agent/KILL`
- 기록: `~/.booking_agent/agent.db`, 로그: `~/.booking_agent/agent.log`

## 설정 (`watches.yaml`)
- `dates`: 앞에 있을수록 우선
- `cancel_policy.tiers`: 비워두면 '모름'으로 처리 → 자동 확정 금지
- `dry_run: true` 기본값. 실제 자동결제는 대상별로 확인한 뒤에만 끈다
- 비밀값은 `.env`에 둔다(`.env.example` 참고, 커밋 금지)
