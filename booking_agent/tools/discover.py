"""NOL 페이지 구조 수집기 (맥북에서 1회 실행).

브라우저가 열리면 직접 날짜 → 입장 시간 선택까지 클릭하고, 단계마다 터미널에서 Enter.
JSON 응답 본문 + 화면 HTML + 스크린샷이 captures/ 에 저장된다.
요청 헤더(쿠키·토큰)는 저장하지 않는다. 가능하면 로그인하지 않은 상태로 실행할 것.

    python tools/discover.py https://leisure-web.yanolja.com/leisure/10367229
"""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

OUT = Path("captures")
MAX_BODY = 2_000_000


async def main(url: str) -> None:
    OUT.mkdir(exist_ok=True)
    n = 0

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
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

        page.on("response", on_response)
        await page.goto(url, wait_until="networkidle")

        step = 0
        while True:
            cmd = await asyncio.to_thread(
                input, "\n화면 저장=Enter / 종료=q  (날짜 클릭 → Enter → 시간 목록 열기 → Enter 순서로) > "
            )
            if cmd.strip().lower() == "q":
                break
            step += 1
            (OUT / f"step{step}.html").write_text(await page.content())
            await page.screenshot(path=str(OUT / f"step{step}.png"), full_page=True)
            print(f"  step{step} 저장 (url: {page.url})")

        await browser.close()
    print(f"\n완료: {OUT.resolve()} — 이 폴더를 zip으로 보내주세요.")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "https://leisure-web.yanolja.com/leisure/10367229"))
