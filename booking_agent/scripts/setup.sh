#!/usr/bin/env bash
# 맥북 최초 설치 (여러 번 실행해도 안전)
set -euo pipefail
cd "$(dirname "$0")/.."

case "$PWD" in
  "$HOME"/Desktop/*|"$HOME"/Documents/*|"$HOME"/Downloads/*)
    echo "⚠️  Desktop/Documents/Downloads 아래에서는 백그라운드 실행(launchd)이 macOS 권한에 막힐 수 있습니다."
    echo "    홈 폴더 바로 아래(예: ~/chatbot)로 옮기는 것을 권장합니다." ;;
esac

if ! xcode-select -p >/dev/null 2>&1; then
  echo "❌ Xcode Command Line Tools 필요: xcode-select --install 실행 후 다시 시도"; exit 1
fi

PY=python3
for cand in python3.13 python3.12 python3.11 python3.10; do
  command -v "$cand" >/dev/null 2>&1 && { PY=$cand; break; }
done
"$PY" -c 'import sys; assert sys.version_info >= (3, 9), sys.version' \
  || { echo "❌ Python 3.9 이상 필요 (brew install python@3.12)"; exit 1; }
echo "Python: $("$PY" --version)"

[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q

mkdir -p "$HOME/.booking_agent"
[ -f .env ] || { cp .env.example .env; chmod 600 .env; }
echo "✅ 설치 완료"
