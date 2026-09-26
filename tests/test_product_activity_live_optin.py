import asyncio
import os
from datetime import timedelta

import httpx
import pytest

from app.core.config import get_settings
from app.mana_operation_ai.application.ports import MobileActivityPort, OperationalTelemetryPort
from app.mana_operation_ai.application.runtime import SystemClock
from app.mana_operation_ai.domain.enums import IntegrationStatus
from app.mana_operation_ai.infrastructure.google_auth import GoogleServiceAccountTokenProvider
from app.mana_operation_ai.infrastructure.retention.firestore import (
    FirestoreMobileActivityAdapter,
)
from app.mana_operation_ai.infrastructure.retention.firestore_operational import (
    FirestoreOperationalTelemetryAdapter,
)
from app.mana_operation_ai.infrastructure.retention.ga4 import Ga4MobileActivityAdapter
from app.mana_operation_ai.infrastructure.retention.manakids import (
    ManakidsAdminActivityAdapter,
)
from app.mana_operation_ai.infrastructure.retention.unavailable import (
    UnavailableMobileActivityAdapter,
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
    assert settings.operation_product_activity_provider in {
        "manakids",
        "manakids_firebase",
        "manakids_ga4",
    }
    assert settings.manakids_api_username is not None
    assert settings.manakids_api_password is not None

    clock = SystemClock()
    mobile_timeout = (
        settings.firebase_request_timeout_seconds
        if settings.operation_product_activity_provider == "manakids_firebase"
        else settings.ga4_request_timeout_seconds
    )
    async with (
        httpx.AsyncClient(timeout=settings.manakids_request_timeout_seconds) as manakids_http,
        httpx.AsyncClient(timeout=mobile_timeout) as mobile_http,
        httpx.AsyncClient(timeout=settings.firebase_request_timeout_seconds) as operational_http,
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
        mobile: MobileActivityPort
        if settings.operation_product_activity_provider == "manakids":
            mobile = UnavailableMobileActivityAdapter(clock=clock)
        elif settings.operation_product_activity_provider == "manakids_firebase":
            assert settings.firebase_project_id is not None
            assert settings.firebase_service_account_file is not None
            mobile = FirestoreMobileActivityAdapter(
                client=mobile_http,
                project_id=settings.firebase_project_id,
                database_id=settings.firebase_database_id,
                collection_id=settings.firebase_activity_collection,
                token_provider=GoogleServiceAccountTokenProvider(
                    str(settings.firebase_service_account_file),
                    scopes=["https://www.googleapis.com/auth/datastore"],
                ),
                clock=clock,
                max_documents=min(settings.firebase_max_activity_documents, 5_000),
                max_retries=settings.firebase_max_retries,
                retry_backoff_seconds=settings.firebase_retry_backoff_seconds,
            )
        else:
            assert settings.ga4_property_id is not None
            assert settings.ga4_service_account_file is not None
            mobile = Ga4MobileActivityAdapter(
                client=mobile_http,
                property_id=settings.ga4_property_id,
                token_provider=GoogleServiceAccountTokenProvider(
                    str(settings.ga4_service_account_file),
                    scopes=["https://www.googleapis.com/auth/analytics.readonly"],
                ),
                clock=clock,
                api_base_url=settings.ga4_api_base_url,
                dimension_limit=min(settings.ga4_dimension_limit, 50),
                max_concurrency=settings.ga4_max_concurrency,
                max_retries=settings.ga4_max_retries,
                retry_backoff_seconds=settings.ga4_retry_backoff_seconds,
            )

        operational: OperationalTelemetryPort | None = None
        if settings.firebase_operational_telemetry_enabled:
            assert settings.firebase_project_id is not None
            token_provider = (
                GoogleServiceAccountTokenProvider(
                    str(settings.firebase_service_account_file),
                    scopes=["https://www.googleapis.com/auth/datastore"],
                )
                if settings.firebase_service_account_file is not None
                else None
            )
            operational = FirestoreOperationalTelemetryAdapter(
                client=operational_http,
                project_id=settings.firebase_project_id,
                database_id=settings.firebase_database_id,
                token_provider=token_provider,
                clock=clock,
                max_documents_per_collection=min(
                    settings.firebase_operational_max_documents_per_collection,
                    5_000,
                ),
                max_retries=settings.firebase_max_retries,
                retry_backoff_seconds=settings.firebase_retry_backoff_seconds,
            )

        health_checks = [backend.health(), mobile.health()]
        if operational is not None:
            health_checks.append(operational.health())
        health = await asyncio.gather(*health_checks)
        if settings.operation_product_activity_provider == "manakids":
            assert health[0].status is IntegrationStatus.HEALTHY
            assert health[1].status is IntegrationStatus.UNCONFIGURED
            assert all(item.status is IntegrationStatus.HEALTHY for item in health[2:])
        else:
            assert all(item.status is IntegrationStatus.HEALTHY for item in health)

        period_end = clock.now()
        period_start = period_end - timedelta(days=1)
        operational_facts = None
        if operational is None:
            backend_facts, mobile_facts = await asyncio.gather(
                backend.collect_activity(period_start=period_start, period_end=period_end),
                mobile.collect_activity(period_start=period_start, period_end=period_end),
            )
        else:
            backend_facts, mobile_facts, operational_facts = await asyncio.gather(
                backend.collect_activity(period_start=period_start, period_end=period_end),
                mobile.collect_activity(period_start=period_start, period_end=period_end),
                operational.collect_telemetry(),
            )

    serialized = backend_facts.model_dump_json() + mobile_facts.model_dump_json()
    if operational_facts is not None:
        serialized += operational_facts.model_dump_json()
    for forbidden in (
        "fullname",
        "parent_phone",
        "subject_id",
        "session_id",
        "search_query",
        "latitude",
        "longitude",
    ):
        assert forbidden not in serialized.lower()
