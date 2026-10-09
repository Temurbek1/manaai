from typing import Protocol

from app.mana_operation_ai.application.ports import ProviderPermanentError
from app.mana_operation_ai.domain.cost_control import (
    CostAttribution,
    CostPeriod,
    CostReservation,
    ResourceUsage,
)


class CostBudgetExceeded(ProviderPermanentError):
    """Admission failed before external I/O; stale evidence may still be displayed."""


class CostLedger(Protocol):
    async def reserve(
        self, usage: ResourceUsage, *, attribution: CostAttribution
    ) -> CostReservation: ...

    async def settle(self, reservation_id: str, *, actual: ResourceUsage) -> None: ...

    async def periods(self) -> list[CostPeriod]: ...
