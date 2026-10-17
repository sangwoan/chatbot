"""알림 채널.

- kakao: 카카오톡 '나에게 보내기' (단방향 알림, 승인 버튼 불가)
- telegram: 알림 + 승인/거절 버튼 (양방향)
- mac: macOS 알림센터 + 소리
- console: 터미널 출력
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import requests

KAKAO_TOKEN_FILE = Path.home() / ".booking_agent" / "kakao_token.json"


class Notifier:
    can_approve = False

    def send(self, text: str, link: str | None = None) -> None:
        raise NotImplementedError

    def request_approval(self, text: str, link: str | None, timeout_s: int) -> bool | None:
        """True=승인, False=거절, None=시간 초과. 승인 미지원 채널은 None."""
        return None


class ConsoleNotifier(Notifier):
    def send(self, text, link=None):
        print(f"\n🔔 {text}" + (f"\n   {link}" if link else ""), flush=True)


class MacNotifier(Notifier):
    def send(self, text, link=None):
        safe = text.replace("\\", "").replace('"', "'")
        subprocess.run(
            ["osascript", "-e", f'display notification "{safe}" with title "예약 에이전트" sound name "Glass"'],
            check=False,
        )


class KakaoNotifier(Notifier):
    def __init__(self):
        self.rest_key = os.environ["KAKAO_REST_API_KEY"]
        self.client_secret = os.environ.get("KAKAO_CLIENT_SECRET")
        if not KAKAO_TOKEN_FILE.exists():
            raise FileNotFoundError(f"{KAKAO_TOKEN_FILE} 없음 — tools/kakao_auth.py 먼저 실행")

    def _token(self) -> str:
        tok = json.loads(KAKAO_TOKEN_FILE.read_text())
        if tok.get("expires_at", 0) - time.time() > 300:
            return tok["access_token"]
        data = {"grant_type": "refresh_token", "client_id": self.rest_key, "refresh_token": tok["refresh_token"]}
        if self.client_secret:
            data["client_secret"] = self.client_secret
        r = requests.post("https://kauth.kakao.com/oauth/token", data=data, timeout=10)
        r.raise_for_status()
        new = r.json()
        tok["access_token"] = new["access_token"]
        tok["expires_at"] = time.time() + new["expires_in"]
        if "refresh_token" in new:  # 만료 1개월 이내면 새 refresh token 발급됨
            tok["refresh_token"] = new["refresh_token"]
        save_kakao_token(tok)
        return tok["access_token"]

    def send(self, text, link=None):
        template = {"object_type": "text", "text": text[:200], "link": {}}
        if link:
            template["link"] = {"web_url": link, "mobile_web_url": link}
            template["button_title"] = "예약하러 가기"
        r = requests.post(
            "https://kapi.kakao.com/v2/api/talk/memo/default/send",
            headers={"Authorization": f"Bearer {self._token()}"},
            data={"template_object": json.dumps(template, ensure_ascii=False)},
            timeout=10,
        )
        r.raise_for_status()


def save_kakao_token(tok: dict) -> None:
    KAKAO_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    KAKAO_TOKEN_FILE.write_text(json.dumps(tok))
    KAKAO_TOKEN_FILE.chmod(0o600)


class TelegramNotifier(Notifier):
    can_approve = True

    def __init__(self):
        self.token = os.environ["TELEGRAM_BOT_TOKEN"]
        self.chat_id = str(os.environ["TELEGRAM_CHAT_ID"])
        self.api = f"https://api.telegram.org/bot{self.token}"
        self.offset = None

    def send(self, text, link=None):
        self._post("sendMessage", chat_id=self.chat_id, text=text + (f"\n{link}" if link else ""))

    def request_approval(self, text, link, timeout_s):
        nonce = os.urandom(4).hex()
        markup = {"inline_keyboard": [[
            {"text": "✅ 승인", "callback_data": f"ok:{nonce}"},
            {"text": "❌ 거절", "callback_data": f"no:{nonce}"},
        ]]}
        body = f"{text}\n\n⏱ {timeout_s // 60}분 안에 응답 없으면 자동 취소" + (f"\n{link}" if link else "")
        self._post("sendMessage", chat_id=self.chat_id, text=body, reply_markup=json.dumps(markup))
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            wait = int(min(30, max(1, deadline - time.time())))
            for upd in self._post("getUpdates", offset=self.offset, timeout=wait, allowed_updates='["callback_query"]'):
                self.offset = upd["update_id"] + 1
                cq = upd.get("callback_query")
                if not cq or str(cq["message"]["chat"]["id"]) != self.chat_id:
                    continue
                action, _, n = cq.get("data", "").partition(":")
                if n != nonce:
                    continue
                self._post("answerCallbackQuery", callback_query_id=cq["id"])
                return action == "ok"
        self.send("⌛ 승인 대기 시간 초과 — 진행하지 않았습니다.")
        return None

    def _post(self, method, **params):
        r = requests.post(f"{self.api}/{method}", data=params, timeout=40)
        r.raise_for_status()
        return r.json()["result"]


CHANNELS = {"console": ConsoleNotifier, "mac": MacNotifier, "kakao": KakaoNotifier, "telegram": TelegramNotifier}


class MultiNotifier(Notifier):
    """여러 채널에 동시에 알림. 승인은 승인 가능한 첫 채널로."""

    def __init__(self, names: list[str]):
        self.channels = []
        for n in names:
            try:
                self.channels.append(CHANNELS[n]())
            except Exception as e:  # 설정 안 된 채널은 건너뛰고 나머지로 진행
                print(f"[notify] {n} 채널 비활성: {e!r}", flush=True)
        if not self.channels:
            self.channels = [ConsoleNotifier()]
        self.can_approve = any(c.can_approve for c in self.channels)

    def send(self, text, link=None):
        for c in self.channels:
            try:
                c.send(text, link)
            except Exception as e:  # 한 채널 실패가 다른 채널을 막지 않도록
                print(f"[notify] {type(c).__name__} 실패: {e}", flush=True)

    def request_approval(self, text, link, timeout_s):
        approver = next((c for c in self.channels if c.can_approve), None)
        for c in self.channels:
            if c is not approver:
                try:
                    c.send("🟡 승인 요청: " + text, link)
                except Exception as e:
                    print(f"[notify] {type(c).__name__} 실패: {e}", flush=True)
        return approver.request_approval(text, link, timeout_s) if approver else None
