from __future__ import annotations

from ..models import Checkout, Slot, Watch


class Adapter:
    """플랫폼 어댑터.

    fetch_slots는 기준과 상관없이 확인한 슬롯을 모두(매진 포함) 반환한다.
    빈 목록은 '파싱 실패'로 간주되어 경고가 발송된다.
    """

    supports_booking = False

    async def start(self) -> None: ...

    async def close(self) -> None: ...

    def urls(self, watch: Watch) -> list[str]:
        """자동으로 여는 주소들. 시작 전에 AccessGate로 정책을 확인한다."""
        return [watch.url]

    async def fetch_slots(self, watch: Watch) -> list[Slot]:
        raise NotImplementedError

    async def prepare_checkout(self, watch: Watch, slot: Slot) -> Checkout:
        """결제 직전 화면까지 진행하고 그 화면의 값을 다시 읽어 반환. 확정 버튼은 누르지 않는다."""
        raise NotImplementedError

    async def confirm(self, checkout: Checkout) -> str:
        """확정 버튼을 누르고 예약 번호를 반환. 확인 실패 시 예외."""
        raise NotImplementedError

    async def abandon(self, checkout: Checkout) -> None:
        """결제 화면을 떠나 자리 점유를 해제."""
