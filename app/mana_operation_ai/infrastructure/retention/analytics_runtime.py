"""Opt-in manual source wiring. Construction and health cause no network I/O."""

import hashlib
import json
from typing import cast

import httpx

from app.core.config import Settings
from app.mana_operation_ai.application.capabilities import CapabilityRegistry
from app.mana_operation_ai.application.cost_control import CostLedger
from app.mana_operation_ai.application.ports import Clock, IdGenerator, OperationRepository
from app.mana_operation_ai.application.retention.analytics_evidence import (
    ManualAnalyticsEvidenceHandler,
)
from app.mana_operation_ai.application.shared_data import SharedDataReader
from app.mana_operation_ai.domain.agent_tools import SourceReadCapability
from app.mana_operation_ai.domain.cost_control import CostAttribution, DataRateCard, ProductScope
from app.mana_operation_ai.domain.first_party_analytics import (
    CHILD_TELEMETRY_CAPABILITY,
    PARENT_ACTIVITY_CAPABILITY,
    ChildTelemetryFacts,
    ParentAnalyticsFacts,
)
from app.mana_operation_ai.domain.shared_data import SourceBinding
from app.mana_operation_ai.infrastructure.google_auth import GoogleServiceAccountTokenProvider
from app.mana_operation_ai.infrastructure.metered_http import MeteredReadHttp
from app.mana_operation_ai.infrastructure.retention.analytics_http import AnalyticsReadHttp
from app.mana_operation_ai.infrastructure.retention.firestore_child_telemetry import (
    FirestoreChildTelemetryAdapter,
)
from app.mana_operation_ai.infrastructure.retention.ga4_parent_analytics import (
    Ga4ParentAnalyticsAdapter,
)


def register_manual_analytics(
    *,
    settings: Settings,
    registry: CapabilityRegistry,
    ledger: CostLedger,
    shared_reader: SharedDataReader,
    repository: OperationRepository,
    clock: Clock,
    ids: IdGenerator,
    clients: list[httpx.AsyncClient],
) -> list[SourceReadCapability]:
    enabled: list[SourceReadCapability] = []

    def meter(
        source: str, key: str, *, firebase: bool = False, oauth: bool = False
    ) -> MeteredReadHttp:
        return MeteredReadHttp(
            ledger=ledger,
            attribution=CostAttribution(
                product=ProductScope.MANA,
                source=source,
                agent_id="retention-agent",
                capability_key=key,
            ),
            maximum_response_bytes=min(
                settings.operation_data_max_response_bytes, 65_536 if oauth else 1_048_576
            ),
            rates=DataRateCard(
                document_usd_per_100k=settings.operation_firestore_document_usd_per_100k
                if firebase
                else 0,
                response_usd_per_gib=settings.operation_firestore_response_usd_per_gib
                if firebase
                else 0,
            ),
        )

    def binding(source: str, revision: str, identity: dict[str, object]) -> SourceBinding:
        # Query shape/limits must NOT reset the source-wide six-hour gate. A different
        # source identity/revision is an explicit operator-owned binding, not model input.
        fingerprint = hashlib.sha256(
            json.dumps(
                {"revision": revision, "identity": identity, "schema": "manual-mana-analytics-v1"},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return SourceBinding(product=ProductScope.MANA, source=source, fingerprint=fingerprint)

    if settings.operation_parent_analytics_enabled:
        assert settings.ga4_service_account_file and settings.ga4_property_id
        assert settings.ga4_parent_stream_id and settings.ga4_parent_property_timezone
        client = httpx.AsyncClient(timeout=settings.ga4_request_timeout_seconds)
        clients.append(client)
        key = PARENT_ACTIVITY_CAPABILITY
        token = GoogleServiceAccountTokenProvider(
            str(settings.ga4_service_account_file),
            scopes=["https://www.googleapis.com/auth/analytics.readonly"],
            client=client,
            metered_http=meter("google_oauth", key, oauth=True),
            clock=clock,
        )
        source = Ga4ParentAnalyticsAdapter(
            http=AnalyticsReadHttp(client, token, meter("google_analytics_4", key)),
            clock=clock,
            property_id=settings.ga4_property_id,
            stream_id=settings.ga4_parent_stream_id,
            timezone=settings.ga4_parent_property_timezone,
        )
        registry.register(
            ManualAnalyticsEvidenceHandler(
                source=source,
                model=ParentAnalyticsFacts,
                binding=binding(
                    "mana_ga4_parent_analytics",
                    settings.operation_parent_analytics_binding_revision,
                    {"property": settings.ga4_property_id, "stream": settings.ga4_parent_stream_id},
                ),
                shared_reader=shared_reader,
                repository=repository,
                clock=clock,
                ids=ids,
                cache_parameters={"timezone": settings.ga4_parent_property_timezone},
            )
        )
        enabled.append(cast(SourceReadCapability, key))
    if settings.operation_child_telemetry_enabled:
        assert settings.firebase_service_account_file and settings.firebase_project_id
        client = httpx.AsyncClient(timeout=settings.firebase_request_timeout_seconds)
        clients.append(client)
        key = CHILD_TELEMETRY_CAPABILITY
        token = GoogleServiceAccountTokenProvider(
            str(settings.firebase_service_account_file),
            scopes=["https://www.googleapis.com/auth/datastore"],
            client=client,
            metered_http=meter("google_oauth", key, oauth=True),
            clock=clock,
        )
        child_source = FirestoreChildTelemetryAdapter(
            http=AnalyticsReadHttp(
                client, token, meter("firestore_child_telemetry", key, firebase=True)
            ),
            clock=clock,
            project_id=settings.firebase_project_id,
            database_id=settings.firebase_database_id,
            sample_limit=settings.firebase_child_sample_limit,
            precise_accuracy_meters=settings.firebase_child_precise_accuracy_meters,
        )
        registry.register(
            ManualAnalyticsEvidenceHandler(
                source=child_source,
                model=ChildTelemetryFacts,
                binding=binding(
                    "mana_firestore_child_telemetry",
                    settings.operation_child_telemetry_binding_revision,
                    {
                        "project": settings.firebase_project_id,
                        "database": settings.firebase_database_id,
                        "collections": ["battery", "children_location"],
                    },
                ),
                shared_reader=shared_reader,
                repository=repository,
                clock=clock,
                ids=ids,
                cache_parameters={
                    "sample_limit": settings.firebase_child_sample_limit,
                    "accuracy": str(settings.firebase_child_precise_accuracy_meters),
                },
            )
        )
        enabled.append(cast(SourceReadCapability, key))
    return enabled
