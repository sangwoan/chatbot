from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class Slot:
    day: date
    start: time
    available: bool
    remaining: int | None = None  # None = 잔여 수량 표시 없음
    unit_price_krw: int | None = None

    @property
    def key(self) -> str:
        return f"{self.day.isoformat()} {self.start:%H:%M}"

    @property
    def visit_at(self) -> datetime:
        return datetime.combine(self.day, self.start, tzinfo=KST)


@dataclass(frozen=True)
class CancelTier:
    """방문 시각 기준 hours_before 시간 이상 남았을 때 적용되는 수수료율."""

    hours_before: float
    fee_ratio: float


@dataclass(frozen=True)
class CancelPolicy:
    tiers: tuple[CancelTier, ...]

    def __post_init__(self):
        if not self.tiers:
            raise ValueError("취소 규정 구간이 비어 있음")
        ordered = sorted(self.tiers, key=lambda t: -t.hours_before)
        ratios = [t.fee_ratio for t in ordered]
        if ratios != sorted(ratios):
            raise ValueError("방문일이 가까울수록 수수료가 내려가는 규정은 지원하지 않음")
        object.__setattr__(self, "tiers", tuple(ordered))

    def fee_ratio_at(self, cancel_at: datetime, visit_at: datetime) -> float:
        hours_left = (visit_at - cancel_at).total_seconds() / 3600
        for tier in self.tiers:
            if hours_left >= tier.hours_before:
                return tier.fee_ratio
        return 1.0

    def low_fee_deadline(self, visit_at: datetime, threshold: float) -> datetime | None:
        """수수료가 threshold 이하로 취소할 수 있는 마지막 시각. 없으면 None."""
        cheap = [t.hours_before for t in self.tiers if t.fee_ratio <= threshold]
        if not cheap:
            return None
        return visit_at - timedelta(hours=min(cheap))

    @classmethod
    def from_dict(cls, raw: dict | None) -> CancelPolicy | None:
        if not raw or not raw.get("tiers"):
            return None
        return cls(tuple(CancelTier(float(t["hours_before"]), float(t["fee_ratio"])) for t in raw["tiers"]))


@dataclass(frozen=True)
class Watch:
    id: str
    adapter: str
    url: str
    dates: tuple[date, ...]
    time_from: time
    time_to: time
    quantity: int
    mode: str = "notify_only"  # notify_only | auto_book
    max_total_krw: int | None = None
    poll_seconds: int = 90
    cancel_policy: CancelPolicy | None = None
    options: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict) -> Watch:
        if raw.get("mode", "notify_only") not in ("notify_only", "auto_book"):
            raise ValueError(f"{raw['id']}: mode는 notify_only 또는 auto_book")
        return cls(
            id=raw["id"],
            adapter=raw["adapter"],
            url=raw["url"],
            dates=tuple(d if isinstance(d, date) else date.fromisoformat(d) for d in raw["dates"]),
            time_from=time.fromisoformat(raw["time_from"]),
            time_to=time.fromisoformat(raw["time_to"]),
            quantity=int(raw["quantity"]),
            mode=raw.get("mode", "notify_only"),
            max_total_krw=raw.get("max_total_krw"),
            poll_seconds=int(raw.get("poll_seconds", 90)),
            cancel_policy=CancelPolicy.from_dict(raw.get("cancel_policy")),
            options=raw.get("options") or {},
        )


@dataclass(frozen=True)
class Checkout:
    """결제 직전 화면에서 다시 읽은 값. 확정 전 재검증에 사용."""

    day: date
    start: time
    quantity: int
    total_krw: int | None
    deposit_krw: int | None
    cancel_policy: CancelPolicy | None
    handle: object = None  # 어댑터 내부 상태(페이지 등)
