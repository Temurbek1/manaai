from datetime import datetime

from app.mana_operation_ai.application.ports import (
    BackendActivityPort,
    Clock,
    MobileActivityPort,
    OperationalTelemetryPort,
)
from app.mana_operation_ai.application.read_budget import FirestoreReadBudget
from app.mana_operation_ai.application.shared_data import SharedDataReader, SharedDataUnavailable
from app.mana_operation_ai.domain.cost_control import ProductScope
from app.mana_operation_ai.domain.enums import IntegrationStatus
from app.mana_operation_ai.domain.models import IntegrationHealth
from app.mana_operation_ai.domain.retention import (
    BackendActivityFacts,
    MobileActivityFacts,
    OperationalTelemetryFacts,
)
from app.mana_operation_ai.domain.shared_data import SourceBinding


class _SharedSource:
    def __init__(self, reader: SharedDataReader, binding: SourceBinding, clock: Clock) -> None:
        self._reader = reader
        self.binding = binding
        self._clock = clock
        self.integration_id = binding.source

    async def health(self) -> IntegrationHealth:
        # Registry/overview polling must never trigger a paid provider read.
        verified = self.binding.product is not ProductScope.UNVERIFIED
        return IntegrationHealth(
            integration_id=self.integration_id,
            status=IntegrationStatus.UNKNOWN if verified else IntegrationStatus.UNCONFIGURED,
            checked_at=self._clock.now(),
            message="External health probes disabled; inspect dated saved evidence instead",
            diagnostics={
                "external_reads": False,
                "product_scope": self.binding.product.value,
                "scope_verified": verified,
            },
        )


class SharedBackendActivity(_SharedSource):
    def __init__(
        self,
        provider: BackendActivityPort,
        reader: SharedDataReader,
        binding: SourceBinding,
        clock: Clock,
    ) -> None:
        super().__init__(reader, binding, clock)
        self._provider = provider

    async def collect_activity(
        self, *, period_start: datetime, period_end: datetime
    ) -> BackendActivityFacts:
        return await self._reader.read(
            binding=self.binding,
            parameters=_rolling_window(period_start, period_end),
            model=BackendActivityFacts,
            load=lambda: self._provider.collect_activity(
                period_start=period_start, period_end=period_end
            ),
        )


class SharedMobileActivity(_SharedSource):
    def __init__(
        self,
        provider: MobileActivityPort,
        reader: SharedDataReader,
        binding: SourceBinding,
        clock: Clock,
        *,
        scope_filter_verified: bool,
        reliable_sync_supported: bool = True,
    ) -> None:
        super().__init__(reader, binding, clock)
        self._provider = provider
        self._filter_verified = scope_filter_verified
        self._sync_supported = reliable_sync_supported

    async def collect_activity(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
        read_budget: FirestoreReadBudget | None = None,
    ) -> MobileActivityFacts:
        if not self._filter_verified:
            raise SharedDataUnavailable(
                "Mobile analytics needs an approved application stream filter"
            )
        if not self._sync_supported:
            raise SharedDataUnavailable(
                "Firestore lacks a verified change/deletion contract; historical scans are disabled"
            )
        return await self._reader.read(
            binding=self.binding,
            parameters=_rolling_window(period_start, period_end),
            model=MobileActivityFacts,
            load=lambda: self._provider.collect_activity(
                period_start=period_start, period_end=period_end, read_budget=read_budget
            ),
        )


class SharedOperationalTelemetry(_SharedSource):
    def __init__(
        self,
        provider: OperationalTelemetryPort,
        reader: SharedDataReader,
        binding: SourceBinding,
        clock: Clock,
        *,
        reliable_sync_supported: bool,
    ) -> None:
        super().__init__(reader, binding, clock)
        self._provider = provider
        self._sync_supported = reliable_sync_supported

    async def collect_telemetry(
        self, *, read_budget: FirestoreReadBudget | None = None
    ) -> OperationalTelemetryFacts:
        if not self._sync_supported:
            raise SharedDataUnavailable(
                "Firestore current-state changes/deletions are unverified; "
                "prefix scans are disabled"
            )
        return await self._reader.read(
            binding=self.binding,
            parameters={"kind": "current-state-v1"},
            model=OperationalTelemetryFacts,
            load=lambda: self._provider.collect_telemetry(read_budget=read_budget),
        )


def _rolling_window(start: datetime, end: datetime) -> dict[str, object]:
    if start.utcoffset() is None or end.utcoffset() is None or end <= start:
        raise ValueError("Shared rolling windows require ordered timezone-aware times")
    # Only the current rolling-window port is exposed. Saved facts retain their
    # ORIGINAL period: reuse is never presented as a new historical query result.
    return {"window_seconds": int((end - start).total_seconds()), "kind": "rolling-v1"}
