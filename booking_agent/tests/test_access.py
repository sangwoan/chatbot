import asyncio
from datetime import datetime

import pytest

from agent.access import (
    MIN_GAP_S, USER_AGENT, AccessGate, PolicyRefused, RateLimited, RobotsRules, SiteBlocked, detect_block,
)
from agent.models import KST, Watch
from agent.runner import Agent, Settings
from agent.store import Store


class Resp:
    def __init__(self, status=200, text="", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}


class Session:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, headers=None, timeout=None, **kw):
        self.calls.append((method, url, headers))
        r = self.routes.get(url, Resp(404))
        return r.pop(0) if isinstance(r, list) else r


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def __call__(self):
        return self.t

    async def sleep(self, s):
        self.slept.append(s)
        self.t += s


def gate(routes, sites=None, store=None):
    clock = Clock()
    g = AccessGate(sites if sites is not None else {"ex.com": {"terms": "allowed"}}, store,
                   session=Session(routes), clock=clock, sleep=clock.sleep)
    return g, clock


def run(coro):
    return asyncio.run(coro)


# ── robots.txt ───────────────────────────────────────────────

def test_robots_longest_match_and_allow_tie():
    r = RobotsRules.parse("User-agent: *\nDisallow: /private\nAllow: /private/ok\nAllow: /p\nDisallow: /p")
    assert not r.allowed("/private/x")
    assert r.allowed("/private/ok/x")
    assert r.allowed("/p")          # 같은 길이면 Allow
    assert r.allowed("/")


def test_robots_wildcard_and_end_anchor():
    r = RobotsRules.parse("User-agent: *\nDisallow: /*?sort=\nDisallow: /*.pdf$")
    assert not r.allowed("/list?sort=1")
    assert r.allowed("/list")
    assert not r.allowed("/a.pdf")
    assert r.allowed("/a.pdf?x=1")


def test_robots_root_only_allow():
    r = RobotsRules.parse("User-agent: *\nDisallow: /\nAllow: /$")
    assert r.allowed("/")
    assert not r.allowed("/booking")


def test_robots_specific_group_beats_star():
    r = RobotsRules.parse("User-agent: booking-agent\nDisallow: /\n\nUser-agent: *\nAllow: /")
    assert not r.allowed("/x")


def test_robots_grouped_agents_share_rules_and_crawl_delay():
    r = RobotsRules.parse("User-agent: googlebot\nUser-agent: *\nDisallow: /x\nCrawl-delay: 10\n")
    assert not r.allowed("/x/1")
    assert r.crawl_delay() == 10


def test_robots_empty_disallow_allows_everything():
    assert RobotsRules.parse("User-agent: *\nDisallow:").allowed("/anything")


# ── 차단 감지 ─────────────────────────────────────────────────

@pytest.mark.parametrize("status,text,blocked", [
    (403, "", True),
    (451, "", True),
    (503, "<title>Just a moment...</title>", True),
    (200, "<html><script src='/cdn-cgi/challenge-platform/x.js'></script></html>", True),
    (200, "<h1>Access Denied</h1> Reference #18.abc", True),
    (200, "<html>" + "정상 페이지 " * 10_000 + "</html>", False),
    (200, "<html><body>예약 가능</body></html>", False),
])
def test_detect_block(status, text, blocked):
    assert (detect_block(status, text) is not None) is blocked


# ── 정책 게이트 ───────────────────────────────────────────────

@pytest.mark.parametrize("site,word", [
    ({}, "약관 확인 전"),
    ({"terms": "banned"}, "약관이 자동 접근을 금지"),
    ({"terms": "allowed", "status": "blocked"}, "막는 사이트"),
])
def test_gate_refuses_by_registry_without_network(site, word):
    g, _ = gate({}, sites={"ex.com": site} if site else {})
    with pytest.raises(PolicyRefused, match=word):
        run(g.check("https://ex.com/a"))
    assert g.session.calls == []


def test_gate_refuses_robots_disallow():
    g, _ = gate({"https://ex.com/robots.txt": Resp(200, "User-agent: *\nDisallow: /api")})
    with pytest.raises(PolicyRefused, match="robots.txt"):
        run(g.request("GET", "https://ex.com/api/rounds"))


def test_gate_treats_robots_403_as_refusal():
    g, _ = gate({"https://ex.com/robots.txt": Resp(403)})
    with pytest.raises(PolicyRefused, match="접근 거부"):
        run(g.check("https://ex.com/a"))


def test_gate_sends_honest_user_agent_and_spaces_requests():
    g, clock = gate({"https://ex.com/a": Resp(200, "ok")})  # robots.txt 404 → 제한 없음
    run(g.request("GET", "https://ex.com/a", headers={"User-Agent": "Mozilla/5.0 fake"}))
    run(g.request("GET", "https://ex.com/a"))
    assert all(h["User-Agent"] == USER_AGENT for _, _, h in g.session.calls)
    assert clock.slept and min(clock.slept) >= MIN_GAP_S - 1e-9


def test_gate_respects_crawl_delay():
    g, clock = gate({
        "https://ex.com/robots.txt": Resp(200, "User-agent: *\nCrawl-delay: 30"),
        "https://ex.com/a": Resp(200, "ok"),
    })
    run(g.request("GET", "https://ex.com/a"))
    run(g.request("GET", "https://ex.com/a"))
    assert max(clock.slept) >= 30 - 1e-9


def test_gate_block_is_recorded_and_never_retried():
    store = Store(":memory:")
    g, _ = gate({"https://ex.com/a": Resp(403, "denied")}, store=store)
    with pytest.raises(SiteBlocked):
        run(g.request("GET", "https://ex.com/a"))
    assert store.blocked_reason("ex.com") == "HTTP 403"
    calls = len(g.session.calls)
    with pytest.raises(PolicyRefused, match="차단 기록"):
        run(g.request("GET", "https://ex.com/a"))
    assert len(g.session.calls) == calls
    assert store.unblock_host("ex.com") and store.blocked_reason("ex.com") is None


def test_gate_rate_limit_backs_off_then_blocks():
    g, clock = gate({"https://ex.com/a": [Resp(429, "", {"Retry-After": "120"}) for _ in range(3)]})
    for _ in range(2):
        with pytest.raises(RateLimited):
            run(g.request("GET", "https://ex.com/a"))
    with pytest.raises(SiteBlocked, match="429"):
        run(g.request("GET", "https://ex.com/a"))
    assert max(clock.slept) >= 300  # 두 번째 이후엔 최소 5분 쉼


# ── 실행 흐름 ────────────────────────────────────────────────

class Notifier:
    can_approve = False

    def __init__(self):
        self.sent = []

    def send(self, text, link=None):
        self.sent.append(text)


class BlockedAdapter:
    supports_booking = False

    async def fetch_slots(self, w):
        raise SiteBlocked("ex.com", "HTTP 403")


def test_runner_stops_watch_when_site_blocks():
    w = Watch.from_dict(dict(id="w", adapter="fake", url="https://ex.com", dates=["2026-11-07"],
                             time_from="10:00", time_to="16:00", quantity=2))
    n = Notifier()
    agent = Agent(Settings.from_dict({}), Store(":memory:"), n, {"fake": BlockedAdapter()},
                  clock=lambda: datetime(2026, 10, 19, 12, 0, tzinfo=KST))
    run(agent.run_watch(w))  # 멈추지 않으면 테스트가 끝나지 않는다
    assert len(n.sent) == 1 and "감시 중단" in n.sent[0] and "우회하지 않습니다" in n.sent[0]


def test_watch_poll_floor_and_enabled_flag():
    base = dict(id="w", adapter="fake", url="https://ex.com", dates=["2026-11-07"],
                time_from="10:00", time_to="16:00", quantity=2)
    assert Watch.from_dict({**base, "poll_seconds": 10}).poll_seconds == 60
    assert Watch.from_dict(base).enabled
    assert not Watch.from_dict({**base, "enabled": False}).enabled
