"""모니터링 루프.

    python -m agent.runner -c watches.yaml            # 상시 실행
    python -m agent.runner -c watches.yaml --once     # 1회 확인
    python -m agent.runner -c watches.yaml --test-notify
    python -m agent.runner --check-url URL            # 새 사이트 온보딩: 정책·robots.txt 판정
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import requests
import yaml

from .access import AccessGate, PolicyRefused, SiteBlocked, host_of, path_of
from .adapters import Adapter, make_adapter
from .criteria import matching_slots
from .models import KST, Checkout, Slot, Watch
from .notify import MultiNotifier, Notifier
from .policy import GateConfig, evaluate
from .store import Store

HOME = Path.home() / ".booking_agent"
KILL_FILE = HOME / "KILL"
ERROR_ALERT_AFTER = 3


@dataclass
class Settings:
    gate: GateConfig
    approval_timeout_s: int = 600
    realert: timedelta = timedelta(minutes=15)
    dry_run: bool = True
    daily_cap_krw: int = 200_000

    @classmethod
    def from_dict(cls, raw: dict) -> Settings:
        return cls(
            gate=GateConfig(
                max_auto_krw=int(raw.get("max_auto_krw", 100_000)),
                max_fee_ratio=float(raw.get("max_cancel_fee_ratio", 0.10)),
                min_buffer=timedelta(hours=float(raw.get("min_cancel_buffer_hours", 24))),
            ),
            approval_timeout_s=int(raw.get("approval_timeout_min", 10)) * 60,
            realert=timedelta(minutes=float(raw.get("realert_min", 15))),
            dry_run=bool(raw.get("dry_run", True)),
            daily_cap_krw=int(raw.get("daily_cap_krw", 200_000)),
        )


def now_kst() -> datetime:
    return datetime.now(KST)


class Agent:
    def __init__(self, settings: Settings, store: Store, notifier: Notifier, adapters: dict[str, Adapter], clock=now_kst):
        self.s = settings
        self.store = store
        self.notifier = notifier
        self.adapters = adapters
        self.clock = clock

    async def tick(self, watch: Watch) -> None:
        if self.store.booked(watch.id):
            return
        adapter = self.adapters[watch.adapter]
        slots = await adapter.fetch_slots(watch)
        if not slots:
            raise RuntimeError("슬롯 0개 — 페이지 구조 변경 또는 파싱 실패 의심")
        now = self.clock()
        matches = matching_slots(watch, slots, now)
        self.store.log(watch.id, "poll", {"slots": len(slots), "matches": [s.key for s in matches]})
        fresh = self.store.slots_to_alert(watch.id, matches, now, self.s.realert)
        if not fresh:
            return

        if watch.mode == "notify_only" or not adapter.supports_booking or KILL_FILE.exists():
            self.notifier.send(_alert_text(watch, fresh), watch.url)
            self.store.log(watch.id, "alert", [s.key for s in fresh])
            return
        await self._try_book(watch, adapter, fresh[0])

    async def _try_book(self, watch: Watch, adapter: Adapter, slot: Slot) -> None:
        checkout = await adapter.prepare_checkout(watch, slot)
        problem = self._recheck(watch, slot, checkout)
        if problem:
            return await self._stop(watch, adapter, checkout, f"재검증 실패: {problem}")

        policy = checkout.cancel_policy or watch.cancel_policy  # 화면에서 못 읽으면 사용자가 설정한 규정
        decision = evaluate(checkout.total_krw, policy, slot.visit_at, self.clock(), self.s.gate)
        summary = _checkout_text(watch, checkout)
        self.store.log(watch.id, "gate", {"slot": slot.key, "reasons": decision.reasons})

        if decision.needs_approval:
            if not self.notifier.can_approve:
                return await self._stop(
                    watch, adapter, checkout, f"승인 필요({', '.join(decision.reasons)}) — 직접 예약해 주세요.\n{summary}"
                )
            approved = await asyncio.to_thread(
                self.notifier.request_approval,
                f"승인 필요: {', '.join(decision.reasons)}\n{summary}",
                watch.url,
                self.s.approval_timeout_s,
            )
            self.store.log(watch.id, "approval", {"slot": slot.key, "approved": approved})
            if not approved:
                return await self._stop(watch, adapter, checkout, None)
            # 승인 대기 동안 화면이 바뀌었을 수 있으므로 다시 읽어 승인한 조건과 비교
            approved_checkout = checkout
            checkout = await adapter.prepare_checkout(watch, slot)
            problem = self._recheck(watch, slot, checkout) or _drift(approved_checkout, checkout)
            if problem:
                return await self._stop(watch, adapter, checkout, f"승인 후 재검증 실패: {problem}")

        if self.s.dry_run:
            return await self._stop(watch, adapter, checkout, f"[드라이런] 확정 직전에서 멈춤\n{summary}")

        ref = await adapter.confirm(checkout)
        self.store.record_booking(watch.id, slot.key, checkout.total_krw, ref)
        self.notifier.send(f"✅ 예약 완료 (예약번호 {ref})\n{summary}", watch.url)

    def _recheck(self, watch: Watch, slot: Slot, c: Checkout) -> str | None:
        if (c.day, c.start) != (slot.day, slot.start):
            return f"일시 불일치 {c.day} {c.start} ≠ {slot.key}"
        if c.quantity != watch.quantity:
            return f"수량 불일치 {c.quantity} ≠ {watch.quantity}"
        if not matching_slots(watch, [Slot(c.day, c.start, True)], self.clock()):
            return "기준 범위 밖"
        if c.total_krw is not None and watch.max_total_krw is not None and c.total_krw > watch.max_total_krw:
            return f"총액 {c.total_krw:,}원 > 한도 {watch.max_total_krw:,}원"
        if c.total_krw is not None and self.store.spent_today() + c.total_krw > self.s.daily_cap_krw:
            return f"일일 자동결제 한도 {self.s.daily_cap_krw:,}원 초과"
        return None

    async def _stop(self, watch: Watch, adapter: Adapter, checkout: Checkout, message: str | None) -> None:
        await adapter.abandon(checkout)
        if message:
            self.notifier.send(message, watch.url)
            self.store.log(watch.id, "stopped", message)

    async def run_watch(self, watch: Watch) -> None:
        errors = 0
        while True:
            if self.store.booked(watch.id):
                self.notifier.send(f"⏹ [{watch.id}] 예약 완료 처리됨 — 감시 종료")
                return
            if max(watch.dates) < self.clock().date():
                self.notifier.send(f"⏹ [{watch.id}] 모든 날짜가 지나 감시 종료")
                return
            try:
                await self.tick(watch)
                if errors >= ERROR_ALERT_AFTER:
                    self.notifier.send(f"🟢 [{watch.id}] 감시 복구됨")
                errors = 0
            except (PolicyRefused, SiteBlocked) as e:
                self.store.log(watch.id, "policy_stop", str(e))
                self.notifier.send(f"⛔ [{watch.id}] 감시 중단: {e}\n우회하지 않습니다. 직접 확인해 주세요.", watch.url)
                return
            except Exception as e:
                errors += 1
                self.store.log(watch.id, "error", repr(e))
                print(f"[{watch.id}] 오류 {errors}회: {e!r}", flush=True)
                if errors == ERROR_ALERT_AFTER:
                    self.notifier.send(f"⚠️ [{watch.id}] 감시 {errors}회 연속 실패: {e}", watch.url)
            await asyncio.sleep(watch.poll_seconds * random.uniform(0.8, 1.2))


def _alert_text(watch: Watch, slots: list[Slot]) -> str:
    lines = [f"🎟 [{watch.id}] 자리 났어요! ({watch.quantity}매 가능)"]
    for s in slots[:5]:
        rem = f" · 잔여 {s.remaining}" if s.remaining is not None else ""
        lines.append(f"• {s.day:%m/%d(%a)} {s.start:%H:%M}{rem}")
    return "\n".join(lines)


def _checkout_text(watch: Watch, c: Checkout) -> str:
    total = f"{c.total_krw:,}원" if c.total_krw is not None else "총액 미확인"
    return f"[{watch.id}] {c.day:%m/%d} {c.start:%H:%M} × {c.quantity} · {total}"


def _drift(before: Checkout, after: Checkout) -> str | None:
    if after.total_krw is None or (before.total_krw is not None and after.total_krw > before.total_krw):
        return f"총액 변경 {before.total_krw} → {after.total_krw}"
    if after.cancel_policy != before.cancel_policy:
        return "취소 규정 변경"
    return None


def load(path: str) -> tuple[Settings, list[str], list[Watch], dict]:
    raw = yaml.safe_load(Path(path).read_text())
    return (
        Settings.from_dict(raw.get("defaults") or {}),
        (raw.get("notify") or {}).get("channels", ["console"]),
        [Watch.from_dict(w) for w in raw.get("watches") or []],
        raw.get("sites") or {},
    )


async def check_url(gate: AccessGate, sites: dict, url: str) -> None:
    """새 사이트 온보딩용: 등록부·robots.txt 판정을 사람이 읽기 좋게 출력."""
    host = host_of(url)
    site = {k.lower(): v for k, v in sites.items()}.get(host) or {}
    rules = await gate.robots(url)
    print(f"호스트: {host}")
    print(f"등록부: terms={site.get('terms', 'unreviewed')} status={site.get('status', '-')} {site.get('note', '')}".rstrip())
    print(f"robots.txt: {'허용' if rules.allowed(path_of(url)) else '금지'} {rules.note}".rstrip())
    print(f"Crawl-delay: {rules.crawl_delay() or '-'}")
    if not rules.allowed(path_of(url)):
        print("판정: 감시 안 함 — robots.txt가 이 경로를 금지(명시적 정책이라 약관과 상관없이 제외)")
        return
    try:
        await gate.check(url)
        print("판정: 감시 가능")
    except PolicyRefused as e:
        print(f"판정: 감시 안 함 — {e}")


async def preflight(gate: AccessGate, adapters: dict[str, Adapter], watches: list[Watch], notifier: Notifier | None) -> list[Watch]:
    """시작 전에 정책을 확인해 감시해도 되는 것만 남긴다."""
    ok = []
    for w in watches:
        try:
            for url in adapters[w.adapter].urls(w):
                await gate.check(url)
            ok.append(w)
        except PolicyRefused as e:
            print(f"[{w.id}] 시작 안 함: {e}", flush=True)
            if notifier:
                notifier.send(f"⛔ [{w.id}] 시작 안 함: {e}", w.url)
    return ok


def load_env(path: Path) -> None:
    """KEY=VALUE 형식의 .env를 환경변수로 (이미 설정된 값은 유지)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        value = value.strip().strip("'\"")
        if sep and value and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="watches.yaml")
    ap.add_argument("--once", action="store_true", help="1회 확인(알림 포함)")
    ap.add_argument("--probe", action="store_true", help="슬롯 전체를 출력만 하고 알림은 보내지 않음")
    ap.add_argument("--headed", action="store_true", help="브라우저 창 띄우기")
    ap.add_argument("--test-notify", action="store_true")
    ap.add_argument("--mark-booked", metavar="WATCH_ID", help="직접 예약 완료 → 해당 감시 종료")
    ap.add_argument("--check-url", metavar="URL", help="새 사이트 온보딩: 등록부·robots.txt 판정만 출력")
    ap.add_argument("--unblock", metavar="HOST", help="차단 기록 삭제 — 사이트 정책이 바뀐 것을 확인한 뒤에만")
    args = ap.parse_args()

    load_env(Path(args.config).resolve().parent / ".env")
    settings, channels, all_watches, sites = load(args.config)
    HOME.mkdir(parents=True, exist_ok=True)
    store = Store(HOME / "agent.db")
    gate = AccessGate(sites, store, session=requests.Session())
    if args.mark_booked:
        store.record_booking(args.mark_booked, "manual", None, "manual")
        print(f"{args.mark_booked}: 예약 완료로 기록 — 실행 중인 감시는 다음 확인 때 종료됩니다.")
        return
    if args.unblock:
        removed = store.unblock_host(args.unblock.lower())
        print(f"{args.unblock}: {'차단 기록 삭제' if removed else '차단 기록 없음'}")
        return
    if args.check_url:
        await check_url(gate, sites, args.check_url)
        return

    notifier = MultiNotifier(channels)
    if args.test_notify:
        notifier.send("예약 에이전트 테스트 알림입니다.", all_watches[0].url if all_watches else None)
        return

    watches = [w for w in all_watches if w.enabled]
    if not watches:
        print("켜져 있는 감시가 없습니다 — watches.yaml의 enabled를 확인하세요.")
        return
    adapters = {name: make_adapter(name, headless=not args.headed, gate=gate) for name in {w.adapter for w in watches}}
    watches = await preflight(gate, adapters, watches, notifier if not (args.probe or args.once) else None)
    if not watches:
        print("정책 확인을 통과한 감시가 없습니다.")
        return
    adapters = {name: a for name, a in adapters.items() if any(w.adapter == name for w in watches)}
    for a in adapters.values():
        await a.start()
    agent = Agent(settings, store, notifier, adapters)
    try:
        if args.probe:
            for w in watches:
                try:
                    slots = await adapters[w.adapter].fetch_slots(w)
                except (PolicyRefused, SiteBlocked) as e:
                    print(f"\n[{w.id}] 중단: {e}")
                    continue
                hits = {s.key for s in matching_slots(w, slots, now_kst())}
                print(f"\n[{w.id}] 슬롯 {len(slots)}개, 기준 충족 {len(hits)}개")
                for s in sorted(slots, key=lambda s: (s.day, s.start)):
                    mark = "★" if s.key in hits else ("○" if s.available else "×")
                    print(f"  {mark} {s.key}  잔여={s.remaining}  단가={s.unit_price_krw}")
        elif args.once:
            for w in watches:
                await agent.tick(w)
        else:
            notifier.send(f"▶️ 감시 시작: {', '.join(w.id for w in watches)}")
            await asyncio.gather(*(agent.run_watch(w) for w in watches))
    finally:
        for a in adapters.values():
            await a.close()


if __name__ == "__main__":
    asyncio.run(main())
