from datetime import datetime
from decimal import Decimal

from app.mana_operation_ai.application.ports import Clock
from app.mana_operation_ai.domain.enums import IntegrationStatus
from app.mana_operation_ai.domain.models import IntegrationHealth
from app.mana_operation_ai.domain.retention import MobileActivityFacts


class UnavailableMobileActivityAdapter:
    """Represent a deliberately unconfigured mobile analytics source without fake data."""

    integration_id = "mobile_product_analytics_unconfigured"

    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock

    async def collect_activity(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
    ) -> MobileActivityFacts:
        return MobileActivityFacts(
            source=self.integration_id,
            period_start=period_start,
            period_end=period_end,
            collected_at=self._clock.now(),
            event_counts={},
            active_subjects=0,
            sessions=0,
            screen_time_seconds=0,
            documents_scanned=0,
            invalid_documents=0,
            completeness=Decimal("0"),
            limitations=[
                "Mobile product analytics is not configured. Zero values are unavailable data, "
                "not observed activity; connect GA4 with read-only server credentials.",
            ],
        )

    async def health(self) -> IntegrationHealth:
        return IntegrationHealth(
            integration_id=self.integration_id,
            status=IntegrationStatus.UNCONFIGURED,
            checked_at=self._clock.now(),
            latency_ms=0,
            message="Mobile product analytics is not configured",
            diagnostics={"mode": "unconfigured", "synthetic_data": False},
        )
