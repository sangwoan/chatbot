"""공개 JSON 응답에서 슬롯을 뽑는 범용 어댑터 (PLAN.md §9).

options.extract:
  items: "data.rounds[*]"                  # 슬롯 목록 경로 (점 · [*] · [숫자])
  date: "playDate"                         # 없으면 요청한 날짜
  date_format: "%Y%m%d"                    # 없으면 ISO(2026-10-24)
  time: "startTime"
  time_format: "%H:%M"                     # 없으면 '11:00' · '1100'
  available: {path: "remainCount", gt: 0}  # eq · ne · gt · ge · lt · le · in · truthy. 경로만 쓰면 참/거짓
  remaining: "remainCount"                 # 선택
  price: "price"                           # 선택, 1인 가격
"""
from __future__ import annotations

import operator
import re
from datetime import date

from ..models import Slot
from .generic import GenericAdapter, to_date, to_int, to_time

OPS = {
    "eq": operator.eq, "ne": operator.ne, "gt": operator.gt, "ge": operator.ge,
    "lt": operator.lt, "le": operator.le, "in": lambda a, b: a in b,
}


def resolve(obj, path: str) -> list:
    cur = [obj]
    for part in re.findall(r"\[\*\]|\[-?\d+\]|[^.\[\]]+", path):
        nxt = []
        for o in cur:
            if part == "[*]":
                nxt.extend(o if isinstance(o, list) else o.values() if isinstance(o, dict) else [])
            elif part.startswith("["):
                i = int(part[1:-1])
                if isinstance(o, list) and -len(o) <= i < len(o):
                    nxt.append(o[i])
            elif isinstance(o, dict) and part in o:
                nxt.append(o[part])
        cur = nxt
    return cur


def first(obj, path: str | None):
    vals = resolve(obj, path) if path else []
    return vals[0] if vals else None


def check(item, cond) -> bool:
    if isinstance(cond, str):
        return bool(first(item, cond))
    value = first(item, cond["path"])
    for name, fn in OPS.items():
        if name not in cond:
            continue
        want = cond[name]
        got = to_int(value) if isinstance(want, (int, float)) and isinstance(value, str) else value
        try:
            if not fn(got, want):
                return False
        except TypeError:
            return False
    if "truthy" in cond and bool(value) != bool(cond["truthy"]):
        return False
    return True


class HttpJsonAdapter(GenericAdapter):
    def parse(self, resp, day: date | None, ex: dict) -> list[Slot]:
        out = []
        for item in resolve(resp.json(), ex["items"]):
            d = to_date(first(item, ex.get("date")), ex.get("date_format"), day)
            t = to_time(first(item, ex.get("time")), ex.get("time_format"))
            if d is None or t is None:
                continue
            out.append(Slot(
                d, t, check(item, ex["available"]),
                remaining=to_int(first(item, ex.get("remaining"))),
                unit_price_krw=to_int(first(item, ex.get("price"))),
            ))
        return out
