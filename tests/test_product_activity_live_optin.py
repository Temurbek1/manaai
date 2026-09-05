import asyncio
import os
from datetime import datetime, timedelta

import httpx
import pytest

from app.core.config import get_settings
from app.mana_operation_ai.application.runtime import SystemClock
from app.mana_operation_ai.domain.enums import IntegrationStatus
from app.mana_operation_ai.domain.retention import BackendActivityFacts, MobileActivityFacts
from app.mana_operation_ai.infrastructure.retention.firestore import (
    FirestoreMobileActivityAdapter,
    GoogleServiceAccountTokenProvider,
)
from app.mana_operation_ai.infrastructure.retention.manakids import (
    ManakidsAdminActivityAdapter,
)

pytestmark = [
    pytest.mark.live_product_activity,
    pytest.mark.skipif(
        os.getenv("PRODUCT_ACTIVITY_LIVE_VERIFY") != "1",
        reason="Live first-party reads require PRODUCT_ACTIVITY_LIVE_VERIFY=1",
    ),
]


async def test_live_first_party_sources_are_readable_and_return_aggregate_facts() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.operation_product_activity_provider == "manakids_firebase"
    assert settings.manakids_api_username is not None
    assert settings.manakids_api_password is not None
    assert settings.firebase_project_id is not None
    assert settings.firebase_service_account_file is not None

    clock = SystemClock()
    async with (
        httpx.AsyncClient(timeout=settings.manakids_request_timeout_seconds) as manakids_http,
        httpx.AsyncClient(timeout=settings.firebase_request_timeout_seconds) as firestore_http,
    ):
        backend = ManakidsAdminActivityAdapter(
            client=manakids_http,
            base_url=settings.manakids_api_base_url,
            username=settings.manakids_api_username,
            password=settings.manakids_api_password.get_secret_value(),
            clock=clock,
            max_retries=settings.manakids_max_retries,
            retry_backoff_seconds=settings.manakids_retry_backoff_seconds,
            max_pages=min(settings.manakids_max_pages, 20),
        )
        mobile = FirestoreMobileActivityAdapter(
            client=firestore_http,
            project_id=settings.firebase_project_id,
            database_id=settings.firebase_database_id,
            collection_id=settings.firebase_activity_collection,
            token_provider=GoogleServiceAccountTokenProvider(
                str(settings.firebase_service_account_file),
            ),
            clock=clock,
            max_documents=min(settings.firebase_max_activity_documents, 5_000),
            max_retries=settings.firebase_max_retries,
            retry_backoff_seconds=settings.firebase_retry_backoff_seconds,
        )
        backend_health = await backend.health()
        mobile_health = await mobile.health()
        assert backend_health.status is IntegrationStatus.HEALTHY
        assert mobile_health.status is IntegrationStatus.HEALTHY

        period_end = clock.now()
        backend_facts, mobile_facts = await _collect_both(
            backend,
            mobile,
            period_start=period_end - timedelta(days=1),
            period_end=period_end,
        )

    serialized = backend_facts.model_dump_json() + mobile_facts.model_dump_json()
    for forbidden in ("fullname", "parent_phone", "subject_id", "session_id", "search_query"):
        assert forbidden not in serialized.lower()


async def _collect_both(
    backend: ManakidsAdminActivityAdapter,
    mobile: FirestoreMobileActivityAdapter,
    *,
    period_start: datetime,
    period_end: datetime,
) -> tuple[BackendActivityFacts, MobileActivityFacts]:
    return await asyncio.gather(
        backend.collect_activity(period_start=period_start, period_end=period_end),
        mobile.collect_activity(period_start=period_start, period_end=period_end),
    )
