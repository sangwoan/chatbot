"""서버가 그려 주는 HTML에서 CSS 선택자로 슬롯을 뽑는 범용 어댑터 (PLAN.md §9).

options.extract:
  items: "table.rounds tr"                 # 슬롯 하나에 해당하는 요소
  date: {attr: "data-date"}                # 또는 {select: ".day", regex: "(\\d{4}-\\d{2}-\\d{2})"}. 없으면 요청 날짜
  date_format: "%Y-%m-%d"
  time: {select: ".time"}                  # 문자열만 쓰면 select로 본다. regex는 첫 그룹
  time_format: "%H:%M"
  available:                               # 적은 조건을 모두 만족해야 예약 가능
    select: "button.reserve:not([disabled])"
    text_contains: "예약가능"
    not_text_contains: "매진"
  remaining: {select: ".remain", regex: "(\\d+)"}
  price: {select: ".price"}
"""
from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup

from ..models import Slot
from .generic import GenericAdapter, to_date, to_int, to_time


def value_of(el, spec) -> str | None:
    if spec is None:
        return None
    if isinstance(spec, str):
        spec = {"select": spec}
    node = el.select_one(spec["select"]) if spec.get("select") else el
    if node is None:
        return None
    val = node.get(spec["attr"]) if spec.get("attr") else node.get_text(" ", strip=True)
    if val is None:
        return None
    if spec.get("regex"):
        m = re.search(spec["regex"], val)
        if not m:
            return None
        val = m.group(1) if m.groups() else m.group(0)
    return val


def is_available(el, cond: dict) -> bool:
    text = el.get_text(" ", strip=True)
    if cond.get("select") and el.select_one(cond["select"]) is None:
        return False
    if cond.get("text_contains") and cond["text_contains"] not in text:
        return False
    if cond.get("not_text_contains") and cond["not_text_contains"] in text:
        return False
    return True


class HtmlAdapter(GenericAdapter):
    def parse(self, resp, day: date | None, ex: dict) -> list[Slot]:
        out = []
        for el in BeautifulSoup(resp.text, "html.parser").select(ex["items"]):
            d = to_date(value_of(el, ex.get("date")), ex.get("date_format"), day)
            t = to_time(value_of(el, ex.get("time")), ex.get("time_format"))
            if d is None or t is None:
                continue
            out.append(Slot(
                d, t, is_available(el, ex.get("available") or {}),
                remaining=to_int(value_of(el, ex.get("remaining"))),
                unit_price_krw=to_int(value_of(el, ex.get("price"))),
            ))
        return out
