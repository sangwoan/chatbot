"""NOL(야놀자) 레저/티켓 어댑터 — 모니터링 전용.

자동 결제는 지원하지 않는다: NOL 결제는 간편결제 비밀번호/카드 인증 단계가 있고
약관상 자동화 접근이 금지되어 있다. 자리가 나면 알림 + 딥링크로 사용자가 직접 결제한다.

TODO(discover): 잔여 회차를 내려주는 API/화면 구조는 tools/discover.py로 수집한 뒤
_parse()를 채운다. 그 전까지 fetch_slots는 NotImplementedError를 낸다.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..models import Slot, Watch
from .base import Adapter

PROFILE_DIR = Path.home() / ".booking_agent" / "browser-profile"


class NolAdapter(Adapter):
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._pw = None
        self._ctx = None

    async def start(self):
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._ctx = await self._pw.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=self.headless, locale="ko-KR", timezone_id="Asia/Seoul"
        )

    async def close(self):
        if self._ctx:
            await self._ctx.close()
        if self._pw:
            await self._pw.stop()

    async def fetch_slots(self, watch: Watch) -> list[Slot]:
        page = await self._ctx.new_page()
        captured: list[tuple[str, object]] = []

        async def on_response(resp):
            if "json" in resp.headers.get("content-type", ""):
                try:
                    captured.append((resp.url, await resp.json()))
                except Exception:
                    pass

        page.on("response", on_response)
        try:
            await page.goto(watch.url, wait_until="networkidle", timeout=45_000)
            return self._parse(watch, captured)
        finally:
            await page.close()

    def _parse(self, watch: Watch, captured: list[tuple[str, object]]) -> list[Slot]:
        raise NotImplementedError(
            "NOL 회차 파싱 미구현 — tools/discover.py 결과로 구현 필요. "
            f"수집된 JSON 응답 {len(captured)}개: " + json.dumps([u for u, _ in captured][:10], ensure_ascii=False)
        )
