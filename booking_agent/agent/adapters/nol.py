"""NOL(야놀자) 레저/티켓 어댑터 — 모니터링 전용.

자동 결제는 지원하지 않는다: NOL 결제는 간편결제 비밀번호/카드 인증 단계가 있고
약관상 자동화 접근이 금지되어 있다. 자리가 나면 알림 + 딥링크로 사용자가 직접 결제한다.

보류(2026-10-18): NOL이 자동화 브라우저를 첫 요청부터 차단해 _parse()는 구현하지 않았다.
watches.yaml의 sites 등록부가 이 호스트를 막고 있어 AccessGate가 시작 전에 거부한다.
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path

from ..models import Slot, Watch
from .base import Adapter

PROFILE_DIR = Path.home() / ".booking_agent" / "browser-profile"


class NolAdapter(Adapter):
    def __init__(self, headless: bool = True, gate=None):
        self.headless = headless
        self.gate = gate
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
        if self.gate:
            await self.gate.check(watch.url)
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
            async with self.gate.turn(watch.url) if self.gate else contextlib.nullcontext():
                resp = await page.goto(watch.url, wait_until="networkidle", timeout=45_000)
                if self.gate:
                    self.gate.inspect(watch.url, resp.status if resp else 0, await page.content())
            return self._parse(watch, captured)
        finally:
            await page.close()

    def _parse(self, watch: Watch, captured: list[tuple[str, object]]) -> list[Slot]:
        raise NotImplementedError(
            "NOL 회차 파싱 미구현 — tools/discover.py 결과로 구현 필요. "
            f"수집된 JSON 응답 {len(captured)}개: " + json.dumps([u for u, _ in captured][:10], ensure_ascii=False)
        )
