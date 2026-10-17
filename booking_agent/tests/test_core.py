import asyncio
from datetime import date, datetime, time, timedelta

import pytest

from agent.criteria import matching_slots
from agent.models import KST, CancelPolicy, CancelTier, Checkout, Slot, Watch
from agent.policy import evaluate
from agent.runner import Agent, Settings
from agent.store import Store

VISIT = datetime(2026, 10, 24, 11, 0, tzinfo=KST)
FREE_UNTIL_24H = CancelPolicy((CancelTier(24, 0.0), CancelTier(0, 1.0)))


def at(month, day, hour, minute=0):
    return datetime(2026, month, day, hour, minute, tzinfo=KST)


def watch(**kw):
    base = dict(
        id="w", adapter="fake", url="https://example.com",
        dates=["2026-10-24", "2026-10-25", "2026-11-01"],
        time_from="11:00", time_to="15:00", quantity=2, max_total_krw=100_000,
        cancel_policy={"tiers": [{"hours_before": 24, "fee_ratio": 0}, {"hours_before": 0, "fee_ratio": 1}]},
    )
    base.update(kw)
    return Watch.from_dict(base)


# ── 결재 게이트 ──────────────────────────────────────────────

def test_gate_auto_when_cheap_and_buffer_over_one_day():
    d = evaluate(22_000, FREE_UNTIL_24H, VISIT, at(10, 20, 10))
    assert not d.needs_approval, d.reasons


def test_gate_requires_approval_when_buffer_under_one_day():
    d = evaluate(22_000, FREE_UNTIL_24H, VISIT, at(10, 22, 12))  # 무료취소 마감까지 23시간
    assert d.needs_approval and "기간" in d.reasons[0]


def test_gate_requires_approval_when_fee_already_high():
    d = evaluate(22_000, FREE_UNTIL_24H, VISIT, at(10, 23, 12))
    assert d.needs_approval and "즉시" in d.reasons[0]


@pytest.mark.parametrize("total,needs", [(99_999, False), (100_000, True), (None, True)])
def test_gate_amount_boundary(total, needs):
    assert evaluate(total, FREE_UNTIL_24H, VISIT, at(10, 1, 9)).needs_approval is needs


@pytest.mark.parametrize("ratio,needs", [(0.10, False), (0.1001, True)])
def test_gate_fee_ratio_boundary(ratio, needs):
    policy = CancelPolicy((CancelTier(0, ratio),))
    assert evaluate(22_000, policy, VISIT, at(10, 1, 9)).needs_approval is needs


def test_gate_unknown_policy_fails_closed():
    assert evaluate(22_000, None, VISIT, at(10, 1, 9)).needs_approval


def test_policy_rejects_decreasing_fee():
    with pytest.raises(ValueError):
        CancelPolicy((CancelTier(24, 0.5), CancelTier(0, 0.0)))


# ── 기준 판정 ────────────────────────────────────────────────

def test_criteria_filters_and_orders():
    w = watch()
    slots = [
        Slot(date(2026, 11, 1), time(11, 0), True),
        Slot(date(2026, 10, 24), time(14, 40), True),
        Slot(date(2026, 10, 24), time(10, 40), True),           # 시간 밖
        Slot(date(2026, 10, 24), time(15, 0), True),            # 경계 포함
        Slot(date(2026, 10, 24), time(15, 20), True),           # 시간 밖
        Slot(date(2026, 10, 25), time(12, 0), True, remaining=1),  # 수량 부족
        Slot(date(2026, 10, 25), time(12, 20), False),          # 매진
        Slot(date(2026, 10, 31), time(12, 0), True),            # 날짜 밖
        Slot(date(2026, 10, 25), time(13, 0), True, unit_price_krw=60_000),  # 한도 초과
    ]
    got = [s.key for s in matching_slots(w, slots, at(10, 17, 12))]
    assert got == ["2026-10-24 14:40", "2026-10-24 15:00", "2026-11-01 11:00"]


def test_criteria_skips_past_slots():
    w = watch()
    assert matching_slots(w, [Slot(date(2026, 10, 24), time(11, 0), True)], at(10, 24, 11, 5)) == []


# ── 알림 중복 방지 ───────────────────────────────────────────

def test_store_alerts_on_open_and_realert():
    st = Store(":memory:")
    s = Slot(date(2026, 10, 24), time(11, 0), True)
    t0 = at(10, 17, 12)
    re = timedelta(minutes=15)
    assert st.slots_to_alert("w", [s], t0, re) == [s]
    assert st.slots_to_alert("w", [s], t0 + timedelta(minutes=5), re) == []
    assert st.slots_to_alert("w", [s], t0 + timedelta(minutes=16), re) == [s]
    assert st.slots_to_alert("w", [], t0 + timedelta(minutes=17), re) == []
    assert st.slots_to_alert("w", [s], t0 + timedelta(minutes=18), re) == [s]  # 닫혔다 다시 열림


# ── 실행 흐름 ────────────────────────────────────────────────

class FakeNotifier:
    def __init__(self, can_approve=False, answer=None):
        self.can_approve = can_approve
        self.answer = answer
        self.sent = []
        self.approvals = []

    def send(self, text, link=None):
        self.sent.append(text)

    def request_approval(self, text, link, timeout_s):
        self.approvals.append((text, timeout_s))
        return self.answer


class FakeAdapter:
    supports_booking = True

    def __init__(self, slots, checkouts):
        self.slots = slots
        self.checkouts = list(checkouts)
        self.confirmed = []
        self.abandoned = 0

    async def fetch_slots(self, w):
        return self.slots

    async def prepare_checkout(self, w, slot):
        return self.checkouts.pop(0)

    async def confirm(self, c):
        self.confirmed.append(c)
        return "R123"

    async def abandon(self, c):
        self.abandoned += 1


SLOT = Slot(date(2026, 10, 24), time(11, 0), True)


def checkout(total=22_000, day=SLOT.day, start=SLOT.start, qty=2):
    return Checkout(day, start, qty, total, total, None)


def run(agent, w):
    asyncio.run(agent.tick(w))


def make(adapter, notifier, now, dry_run=False):
    s = Settings.from_dict({"dry_run": dry_run})
    return Agent(s, Store(":memory:"), notifier, {"fake": adapter}, clock=lambda: now)


def test_notify_only_sends_alert_without_booking():
    ad, nt = FakeAdapter([SLOT], []), FakeNotifier()
    run(make(ad, nt, at(10, 17, 12)), watch(mode="notify_only"))
    assert len(nt.sent) == 1 and "10/24" in nt.sent[0] and not ad.confirmed


def test_auto_book_without_approval_when_gate_passes():
    ad, nt = FakeAdapter([SLOT], [checkout()]), FakeNotifier()
    agent = make(ad, nt, at(10, 17, 12))
    run(agent, watch(mode="auto_book"))
    assert len(ad.confirmed) == 1 and not nt.approvals and agent.store.booked("w")


def test_dry_run_stops_before_confirm():
    ad, nt = FakeAdapter([SLOT], [checkout()]), FakeNotifier()
    run(make(ad, nt, at(10, 17, 12), dry_run=True), watch(mode="auto_book"))
    assert not ad.confirmed and ad.abandoned == 1 and "드라이런" in nt.sent[0]


def test_recheck_mismatch_aborts():
    ad, nt = FakeAdapter([SLOT], [checkout(qty=1)]), FakeNotifier()
    run(make(ad, nt, at(10, 17, 12)), watch(mode="auto_book"))
    assert not ad.confirmed and "수량" in nt.sent[0]


def test_approval_required_and_granted_rechecks_then_books():
    ad = FakeAdapter([SLOT], [checkout(120_000), checkout(120_000)])
    nt = FakeNotifier(can_approve=True, answer=True)
    run(make(ad, nt, at(10, 17, 12)), watch(mode="auto_book", max_total_krw=200_000))
    assert nt.approvals[0][1] == 600 and len(ad.confirmed) == 1


def test_price_rise_after_approval_aborts():
    ad = FakeAdapter([SLOT], [checkout(120_000), checkout(130_000)])
    nt = FakeNotifier(can_approve=True, answer=True)
    run(make(ad, nt, at(10, 17, 12)), watch(mode="auto_book", max_total_krw=200_000))
    assert not ad.confirmed and "총액 변경" in nt.sent[-1]


@pytest.mark.parametrize("answer", [False, None])
def test_rejected_or_timed_out_approval_does_not_book(answer):
    ad = FakeAdapter([SLOT], [checkout(120_000)])
    nt = FakeNotifier(can_approve=True, answer=answer)
    run(make(ad, nt, at(10, 17, 12)), watch(mode="auto_book", max_total_krw=200_000))
    assert not ad.confirmed and ad.abandoned == 1


def test_approval_needed_but_one_way_channel_falls_back_to_manual():
    ad, nt = FakeAdapter([SLOT], [checkout(120_000)]), FakeNotifier(can_approve=False)
    run(make(ad, nt, at(10, 17, 12)), watch(mode="auto_book", max_total_krw=200_000))
    assert not ad.confirmed and "직접 예약" in nt.sent[0]


def test_empty_slot_list_is_treated_as_error():
    with pytest.raises(RuntimeError):
        run(make(FakeAdapter([], []), FakeNotifier(), at(10, 17, 12)), watch())
