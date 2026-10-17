#!/usr/bin/env bash
# 백그라운드 감시 서비스(launchd) 관리
#   install  등록 + 시작 (로그인 시 자동 시작, 비정상 종료 시 재시작)
#   stop     중지 + 등록 해제
#   restart  재시작 (설정 변경 후)
#   status   상태 + 최근 로그
#   logs     로그 실시간 보기
set -euo pipefail
cd "$(dirname "$0")/.."

LABEL=com.booking-agent
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/.booking_agent/agent.log"
DOMAIN="gui/$(id -u)"

case "${1:-status}" in
  install)
    mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.booking_agent"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/caffeinate</string><string>-i</string>
    <string>$PWD/.venv/bin/python</string><string>-m</string><string>agent.runner</string>
    <string>-c</string><string>$PWD/watches.yaml</string>
  </array>
  <key>WorkingDirectory</key><string>$PWD</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
  <key>EnvironmentVariables</key><dict><key>PYTHONUNBUFFERED</key><string>1</string></dict>
</dict></plist>
EOF
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    echo "✅ 감시 서비스 시작 — 로그: $LOG" ;;
  stop)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "⏹ 감시 서비스 중지" ;;
  restart)
    launchctl kickstart -k "$DOMAIN/$LABEL" && echo "🔄 재시작" ;;
  status)
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      launchctl print "$DOMAIN/$LABEL" | grep -E '^\s*(state|pid|last exit code)' || true
    else
      echo "서비스 미등록(중지 상태)"
    fi
    echo "--- 최근 로그 ---"; tail -n 20 "$LOG" 2>/dev/null || echo "(로그 없음)" ;;
  logs)
    tail -f "$LOG" ;;
  *)
    echo "usage: $0 install|stop|restart|status|logs"; exit 1 ;;
esac
