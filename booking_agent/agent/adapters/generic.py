"""설정만으로 동작하는 범용 어댑터의 공통 부분 (PLAN.md §9).

watch.options:
  requests:                     # 생략하면 watch.url 하나를 GET
    - url: "https://example.com/api/rounds?date={date:%Y-%m-%d}"
      method: GET               # GET | POST
      params: {}                # 선택 — 쿼리
      data: {}                  # 선택 — form
      json: {}                  # 선택 — JSON 본문
  extract: {}                   # 어댑터별 추출 규칙 (http_json · html)

url·params·data·json 안에 {date:...}가 있으면 watch.dates의 날짜마다 따로 요청한다.
{date:...}를 쓴 문자열 안의 다른 중괄호는 {{ }}로 적는다. 모든 요청은 AccessGate를 거친다.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time

from ..models import Slot, Watch
from .base import Adapter


def _uses_date(value) -> bool:
    if isinstance(value, str):
        return "{date" in value
    if isinstance(value, dict):
        return any(_uses_date(v) for v in value.values())
    if isinstance(value, list):
        return any(_uses_date(v) for v in value)
    return False


def _render(value, day: date | None):
    if isinstance(value, str):
        return value.format(date=day) if day is not None and "{date" in value else value
    if isinstance(value, dict):
        return {k: _render(v, day) for k, v in value.items()}
    if isinstance(value, list):
        return [_render(v, day) for v in value]
    return value


def planned_requests(watch: Watch) -> list[tuple[date | None, dict]]:
    out = []
    for spec in watch.options.get("requests") or [{"url": watch.url}]:
        for day in (watch.dates if _uses_date(spec) else (None,)):
            out.append((day, _render(spec, day)))
    return out


def to_date(value, fmt: str | None, fallback: date | None) -> date | None:
    if value in (None, ""):
        return fallback
    s = str(value).strip()
    return datetime.strptime(s, fmt).date() if fmt else date.fromisoformat(s[:10])


def to_time(value, fmt: str | None) -> time | None:
    if value in (None, ""):
        return None
    s = str(value).strip()
    if fmt:
        return datetime.strptime(s, fmt).time()
    m = re.search(r"(\d{1,2}):?(\d{2})", s)
    return time(int(m.group(1)), int(m.group(2))) if m else None


def to_int(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else None


class GenericAdapter(Adapter):
    def __init__(self, gate, **_):
        self.gate = gate

    def urls(self, watch: Watch) -> list[str]:
        return sorted({spec["url"] for _, spec in planned_requests(watch)})

    async def fetch_slots(self, watch: Watch) -> list[Slot]:
        ex = watch.options.get("extract") or {}
        slots: dict[str, Slot] = {}
        for day, spec in planned_requests(watch):
            kw = {k: spec[k] for k in ("params", "data", "json") if spec.get(k) is not None}
            resp = await self.gate.request(spec.get("method", "GET").upper(), spec["url"], **kw)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}: {spec['url']}")
            if (resp.encoding or "").lower() in ("", "iso-8859-1"):
                resp.encoding = resp.apparent_encoding  # 문자셋 표기 없는 국내 사이트(EUC-KR 등)
            for s in self.parse(resp, day, ex):
                slots[s.key] = s
        return list(slots.values())

    def parse(self, resp, day: date | None, ex: dict) -> list[Slot]:
        raise NotImplementedError
