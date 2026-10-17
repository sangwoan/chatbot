"""결재 게이트: 자동 확정해도 되는지, 사용자 승인이 필요한지 판정.

규칙 (모두 fail-closed — 모르면 승인 필요):
- 총액 >= max_auto_krw (기본 10만원)
- 예약 시점 취소 수수료 > max_fee_ratio (기본 10%)
- 수수료 10% 이하로 취소 가능한 남은 기간(buffer) < min_buffer (기본 1일)
- 총액 또는 취소 규정을 알 수 없음
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .models import CancelPolicy


@dataclass
class GateConfig:
    max_auto_krw: int = 100_000
    max_fee_ratio: float = 0.10
    min_buffer: timedelta = timedelta(days=1)


@dataclass
class Decision:
    needs_approval: bool
    reasons: list[str] = field(default_factory=list)


def evaluate(
    total_krw: int | None,
    policy: CancelPolicy | None,
    visit_at: datetime,
    booked_at: datetime,
    cfg: GateConfig = GateConfig(),
) -> Decision:
    reasons: list[str] = []

    if total_krw is None:
        reasons.append("총액 확인 불가")
    elif total_krw >= cfg.max_auto_krw:
        reasons.append(f"총액 {total_krw:,}원 ≥ {cfg.max_auto_krw:,}원")

    if policy is None:
        reasons.append("취소 규정 확인 불가")
    else:
        fee_now = policy.fee_ratio_at(booked_at, visit_at)
        deadline = policy.low_fee_deadline(visit_at, cfg.max_fee_ratio)
        if fee_now > cfg.max_fee_ratio:
            reasons.append(f"예약 즉시 취소 수수료 {fee_now:.0%} > {cfg.max_fee_ratio:.0%}")
        elif deadline is None or deadline - booked_at < cfg.min_buffer:
            left = "없음" if deadline is None else _fmt(deadline - booked_at)
            reasons.append(f"수수료 {cfg.max_fee_ratio:.0%} 이하 취소 가능 기간 {left} < {_fmt(cfg.min_buffer)}")

    return Decision(bool(reasons), reasons)


def _fmt(td: timedelta) -> str:
    hours = td.total_seconds() / 3600
    return f"{hours / 24:.1f}일" if hours >= 24 else f"{hours:.1f}시간"
