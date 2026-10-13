from typing import Protocol

from app.mana_operation_ai.domain.first_party_analytics import (
    ChildTelemetryFacts,
    ParentAnalyticsFacts,
)


class AnalyticsEvidencePort[T: ParentAnalyticsFacts | ChildTelemetryFacts](Protocol):
    async def collect(self) -> T: ...
