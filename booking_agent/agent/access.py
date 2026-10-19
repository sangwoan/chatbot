"""자동 접근 게이트 — 모든 자동 요청이 거치는 곳 (PLAN.md §9).

1. sites 등록부: 약관 판정이 allowed·load_only인 호스트만, 차단 기록이 있으면 거부
2. robots.txt 준수 (와일드카드·$·최장 일치, 동률이면 Allow)
3. 호스트별 동시 접속 1개 + 최소 간격(Crawl-delay·Retry-After 존중)
4. 정직한 User-Agent — 바꾸지 않는다
5. 차단 감지 → SiteBlocked. 그 호스트는 자동으로 다시 시도하지 않는다
"""
from __future__ import annotations

import asyncio
import contextlib
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

UA_TOKEN = "booking-agent"
USER_AGENT = f"{UA_TOKEN}/1.0 (personal availability alerts; low rate; obeys robots.txt)"
MIN_GAP_S = 5.0  # 같은 호스트에 연속 요청할 때 최소 간격
ROBOTS_TTL_S = 24 * 3600
ROBOTS_RETRY_S = 3600
RATE_LIMIT_STRIKES = 3
TERMS_OK = ("allowed", "load_only")
BLOCK_STATUS = {401, 403, 407, 451}
CHALLENGE_MARKERS = (
    "cf-chl", "challenge-platform", "just a moment...", "attention required! | cloudflare",
    "_incapsula_resource", "request unsuccessful. incapsula", "captcha-delivery.com", "px-captcha",
    "pardon our interruption", "are you a robot", "unusual traffic", "g-recaptcha", "hcaptcha.com",
)


class PolicyRefused(Exception):
    """정책상 감시하지 않는 대상 (robots.txt 금지 · 약관 금지 · 약관 미확인 · 차단 기록)."""


class SiteBlocked(Exception):
    """사이트가 자동 접근을 막았다. 우회하지 않고 그 호스트 감시를 멈춘다."""

    def __init__(self, host: str, reason: str):
        super().__init__(f"{host}: {reason}")
        self.host, self.reason = host, reason


class RateLimited(RuntimeError):
    """HTTP 429. 다음 확인까지 쉬었다가 다시 시도하고, 연속되면 SiteBlocked가 된다."""


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def path_of(url: str) -> str:
    p = urlsplit(url)
    return (p.path or "/") + (f"?{p.query}" if p.query else "")


def _pattern_matches(pattern: str, path: str) -> bool:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.match(rx + ("$" if anchored else ""), path) is not None


@dataclass
class RobotsRules:
    groups: list[tuple[list[str], list[tuple[bool, str]], float | None]] = field(default_factory=list)
    allow_all: bool = False
    disallow_all: bool = False
    note: str = ""

    @classmethod
    def parse(cls, text: str) -> RobotsRules:
        groups = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        delay: float | None = None
        in_rules = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            key, sep, value = line.partition(":")
            if not sep:
                continue
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                if in_rules:
                    groups.append((agents, rules, delay))
                    agents, rules, delay, in_rules = [], [], None, False
                agents.append(value.lower())
            elif key in ("allow", "disallow") and agents:
                in_rules = True
                if value:
                    rules.append((key == "allow", value))
            elif key == "crawl-delay" and agents:
                in_rules = True
                try:
                    delay = float(value)
                except ValueError:
                    pass
        if agents:
            groups.append((agents, rules, delay))
        return cls(groups)

    def _chosen(self, token: str):
        specific = [g for g in self.groups if any(a != "*" and token.startswith(a) for a in g[0])]
        return specific or [g for g in self.groups if "*" in g[0]]

    def allowed(self, path: str, token: str = UA_TOKEN) -> bool:
        if self.disallow_all:
            return False
        if self.allow_all:
            return True
        best = None
        for allow, pattern in (r for g in self._chosen(token) for r in g[1]):
            if _pattern_matches(pattern, path):
                key = (len(pattern), allow)  # 긴 규칙 우선, 같은 길이면 Allow
                best = key if best is None or key > best else best
        return True if best is None else best[1]

    def crawl_delay(self, token: str = UA_TOKEN) -> float | None:
        delays = [g[2] for g in self._chosen(token) if g[2] is not None]
        return max(delays) if delays else None


def detect_block(status: int, text: str) -> str | None:
    """차단·챌린지 화면이면 사유, 아니면 None (429는 따로 처리)."""
    if status in BLOCK_STATUS:
        return f"HTTP {status}"
    head = text[:60_000].lower()
    if (status in (202, 503) or len(text) < 40_000) and (
        any(m in head for m in CHALLENGE_MARKERS) or ("access denied" in head and "reference #" in head)
    ):
        return "챌린지·CAPTCHA 화면"
    return None


def _retry_after(headers) -> float | None:
    try:
        return float((headers or {}).get("Retry-After", ""))
    except ValueError:
        return None


class AccessGate:
    def __init__(self, sites: dict | None = None, store=None, session=None, clock=time.monotonic, sleep=asyncio.sleep):
        self.sites = {h.lower(): (v or {}) for h, v in (sites or {}).items()}
        self.store = store
        self.session = session
        self.clock, self.sleep = clock, sleep
        self._robots: dict[str, tuple[RobotsRules, float]] = {}
        self._next_at: dict[str, float] = {}
        self._strikes: dict[str, int] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # ── 정책 확인 ──────────────────────────────────────────
    async def check(self, url: str) -> None:
        """감시해도 되는 URL인지 확인. 아니면 PolicyRefused."""
        host = host_of(url)
        blocked = self.store.blocked_reason(host) if self.store else None
        if blocked:
            raise PolicyRefused(f"{host}: 자동 접근 차단 기록({blocked}) — 우회하지 않습니다")
        site = self.sites.get(host, {})
        note = f" — {site['note']}" if site.get("note") else ""
        if site.get("status") == "blocked":
            raise PolicyRefused(f"{host}: 자동 접근을 막는 사이트{note}")
        terms = site.get("terms", "unreviewed")
        if terms == "banned":
            raise PolicyRefused(f"{host}: 약관이 자동 접근을 금지{note}")
        if terms not in TERMS_OK:
            raise PolicyRefused(f"{host}: 약관 확인 전 — watches.yaml의 sites에 판정을 기록해야 시작합니다")
        rules = await self.robots(url)
        if not rules.allowed(path_of(url)):
            raise PolicyRefused(f"{host}: robots.txt가 {path_of(url)} 접근을 금지{' (' + rules.note + ')' if rules.note else ''}")

    async def robots(self, url: str) -> RobotsRules:
        p = urlsplit(url)
        root = f"{p.scheme}://{p.netloc}"
        hit = self._robots.get(root)
        if hit and hit[1] > self.clock():
            return hit[0]
        try:
            async with self.turn(root):
                resp = await asyncio.to_thread(self._send, "GET", root + "/robots.txt")
            status, text = resp.status_code, resp.text
        except Exception:
            status, text = None, ""
        if status is None or status >= 500:
            rules, ttl = RobotsRules(disallow_all=True, note="robots.txt 확인 실패, 1시간 뒤 다시 확인"), ROBOTS_RETRY_S
        elif status in (401, 403):
            rules, ttl = RobotsRules(disallow_all=True, note=f"robots.txt부터 접근 거부(HTTP {status})"), ROBOTS_TTL_S
        elif status >= 400:
            rules, ttl = RobotsRules(allow_all=True), ROBOTS_TTL_S
        else:
            rules, ttl = RobotsRules.parse(text), ROBOTS_TTL_S
        self._robots[root] = (rules, self.clock() + ttl)
        return rules

    # ── 요청 ──────────────────────────────────────────────
    @contextlib.asynccontextmanager
    async def turn(self, url: str):
        """호스트별로 한 번에 하나, 최소 간격을 지켜 차례를 기다린다."""
        host = host_of(url)
        async with self._locks.setdefault(host, asyncio.Lock()):
            wait = self._next_at.get(host, 0.0) - self.clock()
            if wait > 0:
                await self.sleep(wait)
            try:
                yield
            finally:
                self._next_at[host] = max(self._next_at.get(host, 0.0), self.clock() + self._gap(url))

    def _gap(self, url: str) -> float:
        p = urlsplit(url)
        hit = self._robots.get(f"{p.scheme}://{p.netloc}")
        delay = hit[0].crawl_delay() if hit else None
        return max(MIN_GAP_S, float(self.sites.get(host_of(url), {}).get("min_gap_s", 0)), delay or 0)

    def _send(self, method: str, url: str, **kw):
        headers = {**(kw.pop("headers", None) or {}), "User-Agent": USER_AGENT}
        return self.session.request(method, url, headers=headers, timeout=20, **kw)

    async def request(self, method: str, url: str, **kw):
        """정책 확인 → 차례 대기 → 요청 → 차단 감지. 응답(requests.Response 호환)을 반환."""
        await self.check(url)
        async with self.turn(url):
            resp = await asyncio.to_thread(self._send, method, url, **kw)
            self.inspect(url, resp.status_code, resp.text, resp.headers)
        return resp

    def inspect(self, url: str, status: int, text: str, headers=None) -> None:
        """응답이 차단이면 SiteBlocked, 429면 RateLimited. 브라우저 어댑터도 페이지를 연 뒤 호출한다."""
        host = host_of(url)
        if status == 429:
            n = self._strikes[host] = self._strikes.get(host, 0) + 1
            pause = max(_retry_after(headers) or 0, 300 * n)
            self._next_at[host] = max(self._next_at.get(host, 0.0), self.clock() + pause)
            if n >= RATE_LIMIT_STRIKES:
                self._block(host, f"HTTP 429 {n}회 연속")
            raise RateLimited(f"{host}: HTTP 429 — {int(pause)}초 쉬고 다시 확인")
        self._strikes.pop(host, None)
        reason = detect_block(status, text or "")
        if reason:
            self._block(host, reason)

    def _block(self, host: str, reason: str) -> None:
        if self.store:
            self.store.block_host(host, reason)
        raise SiteBlocked(host, reason)
