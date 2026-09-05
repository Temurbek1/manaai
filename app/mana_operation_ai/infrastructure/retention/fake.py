from datetime import datetime
from decimal import Decimal

from app.mana_operation_ai.application.ports import Clock
from app.mana_operation_ai.domain.enums import ActivityEventType, IntegrationStatus
from app.mana_operation_ai.domain.models import IntegrationHealth
from app.mana_operation_ai.domain.retention import BackendActivityFacts, MobileActivityFacts


class FakeBackendActivityAdapter:
    integration_id = "fake_manakids_admin_api"

    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock

    async def collect_activity(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
    ) -> BackendActivityFacts:
        return BackendActivityFacts(
            source=self.integration_id,
            period_start=period_start,
            period_end=period_end,
            collected_at=self._clock.now(),
            parent_accounts_joined=140,
            child_accounts_joined=165,
            total_children=2_400,
            children_with_app_usage=1_730,
            children_with_realtime_feature_usage=620,
            completeness=Decimal("1"),
            source_request_ids=["fake-manakids-activity-v1"],
            limitations=[],
        )

    async def health(self) -> IntegrationHealth:
        now = self._clock.now()
        return IntegrationHealth(
            integration_id=self.integration_id,
            status=IntegrationStatus.HEALTHY,
            checked_at=now,
            last_success_at=now,
            latency_ms=0,
            message="Deterministic Manakids Admin API fixture is ready",
            diagnostics={"mode": "fake_read_only"},
        )


class FakeMobileActivityAdapter:
    integration_id = "fake_firestore_activity"

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
            event_counts={
                ActivityEventType.APP_OPEN: 8_900,
                ActivityEventType.APP_CLOSE: 8_400,
                ActivityEventType.SCREEN_VIEW: 31_200,
                ActivityEventType.BUTTON_CLICK: 17_100,
                ActivityEventType.SEARCH: 760,
                ActivityEventType.NAVIGATION: 22_300,
                ActivityEventType.REGISTRATION_STARTED: 180,
                ActivityEventType.REGISTRATION_COMPLETED: 165,
                ActivityEventType.FORM_COMPLETED: 910,
                ActivityEventType.FILE_UPLOADED: 340,
                ActivityEventType.FEATURE_USED: 12_400,
                ActivityEventType.SCREEN_TIME: 30_500,
            },
            dimension_counts={
                "screen_views": {"dashboard": 12_100, "child_profile": 8_300},
                "button_clicks": {"open_child_profile": 5_200, "open_report": 2_100},
                "feature_uses": {"app_usage": 4_700, "screen_share": 1_100},
                "navigation": {"dashboard>child_profile": 4_900},
                "forms_completed": {"registration": 165, "profile_settings": 220},
                "uploads_by_type": {"image": 240, "document": 100},
                "search_usage": {"with_query": 760, "with_filters": 420, "with_sort": 180},
                "screen_time_seconds_by_screen": {
                    "dashboard": 680_000,
                    "child_profile": 410_000,
                },
            },
            sequence_counts={
                "app_open>screen_view": 8_500,
                "screen_view>navigation": 6_200,
                "navigation>feature_used": 4_300,
            },
            active_subjects=1_820,
            sessions=8_900,
            screen_time_seconds=1_480_000,
            documents_scanned=134_055,
            invalid_documents=0,
            completeness=Decimal("1"),
            source_request_ids=["fake-firestore-activity-v1"],
            limitations=[],
        )

    async def health(self) -> IntegrationHealth:
        now = self._clock.now()
        return IntegrationHealth(
            integration_id=self.integration_id,
            status=IntegrationStatus.HEALTHY,
            checked_at=now,
            last_success_at=now,
            latency_ms=0,
            message="Deterministic Firestore activity fixture is ready",
            diagnostics={"mode": "fake_read_only"},
        )
