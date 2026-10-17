"""카카오 '나에게 보내기' 토큰 최초 발급 (1회).

사전 준비: developers.kakao.com 에서 앱 생성 → REST API 키 확인
  - 카카오 로그인 활성화, Redirect URI: http://localhost:8765/callback
  - 동의항목: '카카오톡 메시지 전송(talk_message)' 사용
  - 플랫폼 > Web 사이트 도메인: https://leisure-web.yanolja.com , https://nol.yanolja.com

    KAKAO_REST_API_KEY=... python tools/kakao_auth.py
"""
import os
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent.notify import KakaoNotifier, save_kakao_token  # noqa: E402

REDIRECT = "http://localhost:8765/callback"
code_holder: dict = {}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        code_holder["code"] = qs.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("인증 완료. 이 창을 닫아도 됩니다.".encode())

    def log_message(self, *args):
        pass


def main() -> None:
    key = os.environ["KAKAO_REST_API_KEY"]
    url = "https://kauth.kakao.com/oauth/authorize?" + urlencode(
        {"client_id": key, "redirect_uri": REDIRECT, "response_type": "code", "scope": "talk_message"}
    )
    print("브라우저에서 카카오 로그인/동의를 진행하세요:\n", url)
    webbrowser.open(url)
    server = HTTPServer(("localhost", 8765), Handler)
    while "code" not in code_holder:
        server.handle_request()
    if not code_holder["code"]:
        sys.exit("인증 코드 없음 — 동의를 취소했거나 Redirect URI 설정 확인")

    data = {"grant_type": "authorization_code", "client_id": key, "redirect_uri": REDIRECT, "code": code_holder["code"]}
    if os.environ.get("KAKAO_CLIENT_SECRET"):
        data["client_secret"] = os.environ["KAKAO_CLIENT_SECRET"]
    r = requests.post("https://kauth.kakao.com/oauth/token", data=data, timeout=10)
    r.raise_for_status()
    tok = r.json()
    save_kakao_token({
        "access_token": tok["access_token"],
        "refresh_token": tok["refresh_token"],
        "expires_at": time.time() + tok["expires_in"],
    })
    KakaoNotifier().send("✅ 예약 에이전트 카카오 알림 연결 완료", "https://leisure-web.yanolja.com/leisure/10367229")
    print("토큰 저장 + 테스트 메시지 발송 완료. 카카오톡 '나와의 채팅'을 확인하세요.")


if __name__ == "__main__":
    main()
