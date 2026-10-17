"""NOL 페이지 구조 수집기.

JSON 응답 본문 + 화면 HTML + 스크린샷을 captures/ 에 저장한다.
요청 헤더(쿠키·토큰)는 저장하지 않는다. 로그인하지 않은 상태로 실행할 것.

    python tools/discover.py                 # 수동: 브라우저에서 직접 클릭하고 단계마다 Enter
    python tools/discover.py --auto          # 자동: 페이지 로드 후 대상 날짜 클릭을 시도하며 단계별 저장
"""
import argparse
import asyncio
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

OUT = Path("captures")
MAX_BODY = 2_000_000
DEFAULT_URL = "https://leisure-web.yanolja.com/leisure/10367229"
DEFAULT_DATES = "2026-10-24,2026-10-25,2026-11-01"


async def main(url: str, auto: bool, dates: list[date]) -> None:
    OUT.mkdir(exist_ok=True)
    n = 0
    step = 0

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=auto)
        page = await browser.new_page(locale="ko-KR", timezone_id="Asia/Seoul")

        async def on_response(resp):
            nonlocal n
            host = urlparse(resp.url).hostname or ""
            if "json" not in resp.headers.get("content-type", "") or not any(k in host for k in ("yanolja", "nol")):
                return
            try:
                body = await resp.text()
            except Exception:
                return
            n += 1
            (OUT / f"{n:03d}.json").write_text(json.dumps({
                "url": resp.url,
                "method": resp.request.method,
                "status": resp.status,
                "post_data": resp.request.post_data,
                "body": body[:MAX_BODY],
            }, ensure_ascii=False, indent=1))
            print(f"  [{n:03d}] {resp.request.method} {resp.url[:120]}")

        async def snapshot(label: str):
            nonlocal step
            step += 1
            (OUT / f"step{step}-{label}.html").write_text(await page.content())
            await page.screenshot(path=str(OUT / f"step{step}-{label}.png"), full_page=True)
            print(f"  step{step}-{label} 저장 (url: {page.url})")

        page.on("response", on_response)
        await page.goto(url, wait_until="networkidle", timeout=60_000)
        await snapshot("loaded")

        if auto:
            await auto_explore(page, dates, snapshot)
        else:
            while True:
                cmd = await asyncio.to_thread(
                    input, "\n화면 저장=Enter / 종료=q  (날짜 클릭 → Enter → 시간 목록 열기 → Enter 순서로) > "
                )
                if cmd.strip().lower() == "q":
                    break
                await snapshot("manual")

        await browser.close()
    print(f"\n완료: {OUT.resolve()} (JSON {n}개, 화면 {step}개)")


async def auto_explore(page, dates: list[date], snapshot) -> None:
    """예매/구매 버튼 → 날짜 숫자 클릭을 시도. 실패해도 수집된 것까지는 남긴다."""
    for label in ("예매하기", "구매하기", "날짜 선택", "옵션 선택"):
        btn = page.get_by_text(label, exact=True)
        if await btn.count():
            try:
                await btn.first.click(timeout=5_000)
                await page.wait_for_load_state("networkidle")
                await snapshot(f"click-{label}")
                break
            except Exception as e:
                print(f"  '{label}' 클릭 실패: {e}")

    for d in dates:
        day = page.get_by_text(re.compile(rf"^\s*{d.day}\s*$"))
        count = await day.count()
        print(f"  {d} → '{d.day}' 텍스트 요소 {count}개")
        for i in range(count):
            el = day.nth(i)
            if not await el.is_visible():
                continue
            try:
                await el.click(timeout=3_000)
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(1_500)
                await snapshot(f"date-{d.isoformat()}")
                break
            except Exception:
                continue


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", default=DEFAULT_URL)
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--dates", default=DEFAULT_DATES)
    a = ap.parse_args()
    asyncio.run(main(a.url, a.auto, [date.fromisoformat(x) for x in a.dates.split(",")]))
