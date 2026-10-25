"""One shared scheduled family/day read; existing tariff fan-out and read ceilings remain."""

from typing import Any, Protocol

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.day_usage_service import FamilyDayUsageService
from app.mana_ai.application.inventory_tariffs import TariffCollectionService
from app.mana_ai.domain.family_day_usage import DayUsageReceipt, DayUsageTarget
from app.mana_ai.domain.family_sources import FamilySourceReceipt, FamilySourceTarget


class DayObservation(Protocol):
    async def observe_day(self, target: DayUsageTarget) -> DayUsageReceipt: ...


class DatedCollectionService(TariffCollectionService):
    def __init__(
        self,
        *,
        day_usage: FamilyDayUsageService | None,
        day_observations: DayObservation,
        **collection: Any,
    ) -> None:
        self._day_usage, self._day_observations = day_usage, day_observations
        super().__init__(**collection)

    async def _read_source(
        self, target: FamilySourceTarget | DayUsageTarget
    ) -> FamilySourceReceipt | DayUsageReceipt:
        if not isinstance(target, DayUsageTarget):
            return await super()._read_source(target)
        if self._day_usage is None:
            raise ParentChatError("family_source_not_enabled", 503)
        return await self._day_usage.read_for_analysis(target)

    async def _observe_source(
        self, target: FamilySourceTarget | DayUsageTarget
    ) -> FamilySourceReceipt | DayUsageReceipt:
        if isinstance(target, DayUsageTarget):
            return await self._day_observations.observe_day(target)
        return await super()._observe_source(target)
