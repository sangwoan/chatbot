from __future__ import annotations

from datetime import datetime

from .models import Slot, Watch


def matching_slots(watch: Watch, slots: list[Slot], now: datetime) -> list[Slot]:
    """사용자 기준에 맞는 슬롯을 우선순위(날짜 목록 순서 → 이른 시간) 순으로 반환."""
    order = {d: i for i, d in enumerate(watch.dates)}
    ok = [s for s in slots if _matches(watch, s, now)]
    return sorted(ok, key=lambda s: (order[s.day], s.start))


def _matches(watch: Watch, s: Slot, now: datetime) -> bool:
    if not s.available or s.day not in watch.dates:
        return False
    if not (watch.time_from <= s.start <= watch.time_to):
        return False
    if s.remaining is not None and s.remaining < watch.quantity:
        return False
    if s.visit_at <= now:
        return False
    if watch.max_total_krw is not None and s.unit_price_krw is not None:
        if s.unit_price_krw * watch.quantity > watch.max_total_krw:
            return False
    return True
