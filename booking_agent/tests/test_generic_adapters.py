import asyncio
from datetime import date, time

from agent.adapters import make_adapter
from agent.adapters.generic import planned_requests
from agent.adapters.http_json import check, resolve
from agent.models import Watch

ROUNDS = {"data": {"rounds": [
    {"playDate": "20261107", "startTime": "10:00", "remainCount": 0, "price": "11,000원"},
    {"playDate": "20261107", "startTime": "10:20", "remainCount": "3", "price": 11000},
    {"playDate": "20261107", "startTime": "", "remainCount": 5},
]}}

HTML = """
<table class="rounds">
  <tr class="round" data-date="2026-11-07"><td class="time">10:00</td><td class="remain">잔여 0</td>
    <td><button class="reserve" disabled>매진</button></td></tr>
  <tr class="round" data-date="2026-11-07"><td class="time">10:20</td><td class="remain">잔여 4석</td>
    <td class="price">11,000원</td><td><button class="reserve">예약하기</button></td></tr>
</table>
"""


class Resp:
    def __init__(self, data=None, text="", status=200):
        self._data, self.text, self.status_code = data, text, status
        self.encoding, self.apparent_encoding = "utf-8", "utf-8"

    def json(self):
        return self._data


class FakeGate:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    async def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.resp


def watch(adapter, options):
    return Watch.from_dict(dict(id="w", adapter=adapter, url="https://ex.com/p", dates=["2026-11-07", "2026-11-08"],
                                time_from="10:00", time_to="16:00", quantity=2, options=options))


# ── 요청 계획 ────────────────────────────────────────────────

def test_requests_with_date_template_repeat_per_date():
    w = watch("http_json", {"requests": [
        {"url": "https://ex.com/api?d={date:%Y%m%d}"},
        {"url": "https://ex.com/api/all", "json": {"q": "{{literal}}"}},
    ]})
    got = [(d, spec["url"]) for d, spec in planned_requests(w)]
    assert got == [
        (date(2026, 11, 7), "https://ex.com/api?d=20261107"),
        (date(2026, 11, 8), "https://ex.com/api?d=20261108"),
        (None, "https://ex.com/api/all"),
    ]


def test_requests_default_to_watch_url():
    assert [s["url"] for _, s in planned_requests(watch("html", {}))] == ["https://ex.com/p"]


# ── JSON ────────────────────────────────────────────────────

def test_json_path_and_conditions():
    assert resolve(ROUNDS, "data.rounds[1].startTime") == ["10:20"]
    assert len(resolve(ROUNDS, "data.rounds[*]")) == 3
    assert check({"s": "AVAILABLE"}, {"path": "s", "eq": "AVAILABLE"})
    assert not check({"s": "SOLD_OUT"}, {"path": "s", "in": ["AVAILABLE", "FEW"]})
    assert check({"soldOut": False}, {"path": "soldOut", "truthy": False})
    assert check({"n": "3"}, {"path": "n", "gt": 0})      # 숫자 문자열도 비교
    assert not check({}, {"path": "n", "gt": 0})


def test_http_json_extracts_slots():
    options = {
        "requests": [{"url": "https://ex.com/api?d={date:%Y%m%d}"}],
        "extract": {"items": "data.rounds[*]", "date": "playDate", "date_format": "%Y%m%d", "time": "startTime",
                    "available": {"path": "remainCount", "gt": 0}, "remaining": "remainCount", "price": "price"},
    }
    g = FakeGate(Resp(ROUNDS))
    slots = asyncio.run(make_adapter("http_json", gate=g, headless=True).fetch_slots(watch("http_json", options)))
    assert len(g.calls) == 2  # 날짜마다 요청
    by_key = {s.key: s for s in slots}
    assert set(by_key) == {"2026-11-07 10:00", "2026-11-07 10:20"}
    assert not by_key["2026-11-07 10:00"].available and by_key["2026-11-07 10:00"].unit_price_krw == 11000
    s = by_key["2026-11-07 10:20"]
    assert s.available and s.remaining == 3 and s.start == time(10, 20)


# ── HTML ────────────────────────────────────────────────────

def test_html_extracts_slots():
    options = {"extract": {
        "items": "tr.round", "date": {"attr": "data-date"}, "time": ".time",
        "available": {"select": "button.reserve:not([disabled])", "not_text_contains": "매진"},
        "remaining": {"select": ".remain", "regex": r"(\d+)"}, "price": {"select": ".price"},
    }}
    slots = asyncio.run(make_adapter("html", gate=FakeGate(Resp(text=HTML))).fetch_slots(watch("html", options)))
    by_key = {s.key: s for s in slots}
    sold, open_ = by_key["2026-11-07 10:00"], by_key["2026-11-07 10:20"]
    assert not sold.available and sold.remaining == 0
    assert open_.available and open_.remaining == 4 and open_.unit_price_krw == 11000


def test_html_uses_requested_date_when_page_has_none():
    html = '<ul><li class="slot"><span class="t">14:00</span> 예약가능</li></ul>'
    options = {"requests": [{"url": "https://ex.com/day?d={date:%Y-%m-%d}"}],
               "extract": {"items": "li.slot", "time": ".t", "available": {"text_contains": "예약가능"}}}
    slots = asyncio.run(make_adapter("html", gate=FakeGate(Resp(text=html))).fetch_slots(watch("html", options)))
    assert sorted(s.key for s in slots) == ["2026-11-07 14:00", "2026-11-08 14:00"]
    assert all(s.available for s in slots)
