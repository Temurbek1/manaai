"""Explicit source wiring; construction performs no Google/provider reads."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.core.config import Settings
from app.mana_ai.application.chat_ports import ParentChildrenSource
from app.mana_ai.application.family_collection import FamilyCollectionService
from app.mana_ai.application.family_sources import FamilySourceService
from app.mana_ai.domain.family_sources import FamilySourceKey
from app.mana_ai.domain.source_safety import SourceSafetyPolicy
from app.services.family_collection_store import SqliteFamilyCollectionStore
from app.services.family_google_auth import FamilyFirestoreToken
from app.services.firestore_child_battery import FirestoreChildBatterySource
from app.services.manakids_child_usage import ManakidsChildUsageSource, ManakidsReadToken
from app.services.manakids_family_inventory import ManakidsFamilyInventory
from app.services.multi_family_source_store import SqliteMultiFamilySourceStore
from app.services.source_review_cache import SqliteSourceReviewCache
from app.services.source_safety_store import SqliteSourceSafetyStore


@dataclass(frozen=True)
class FamilySourceRuntime:
    reads: FamilySourceService
    store: SqliteSourceSafetyStore
    safety_policy: SourceSafetyPolicy
    collection: FamilyCollectionService | None = None
    collection_store: SqliteFamilyCollectionStore | None = None


async def family_source_runtime(
    settings: Settings,
    client: httpx.AsyncClient,
    children: ParentChildrenSource,
    *,
    clock: Callable[[], datetime],
    account_auth: ManakidsReadToken | None = None,
) -> FamilySourceRuntime | None:
    if not settings.mana_family_sources_enabled:
        return None
    if (
        settings.mana_family_app_usage_enabled or settings.mana_family_collection_enabled
    ) and account_auth is None:
        raise ValueError("The app-usage source requires the shared MANA authentication port")
    assert settings.firebase_project_id and settings.firebase_service_account_file
    auth = FamilyFirestoreToken(
        client,
        settings.firebase_service_account_file,
        project_id=settings.firebase_project_id,
        clock=clock,
        timeout_seconds=min(15, settings.mana_family_source_timeout_seconds),
    )
    policy = SourceSafetyPolicy(
        timezone=settings.mana_parent_chat_timezone,
        maximum_age_seconds=settings.mana_family_source_maximum_age_seconds,
    )
    store_class = (
        SqliteMultiFamilySourceStore
        if settings.mana_family_app_usage_enabled
        else SqliteSourceSafetyStore
    )
    store = (
        SqliteSourceReviewCache(
            settings.mana_family_source_database_path,
            binding=(
                f"mana:firebase:{settings.firebase_project_id}:"
                f"{settings.firebase_database_id}:child-battery-v1"
            ),
            limits=settings.mana_family_source_limits,
            policy=policy,
            enabled=settings.mana_family_source_safety_enabled,
            review_policy=settings.mana_family_source_review_policy,
        )
        if settings.mana_family_source_reviews_enabled
        else store_class(
            settings.mana_family_source_database_path,
            binding=(
                f"mana:firebase:{settings.firebase_project_id}:"
                f"{settings.firebase_database_id}:child-battery-v1"
            ),
            limits=settings.mana_family_source_limits,
            policy=policy,
            enabled=settings.mana_family_source_safety_enabled,
        )
    )
    await store.initialize()
    source = FirestoreChildBatterySource(
        client,
        auth,
        project_id=settings.firebase_project_id,
        database_id=settings.firebase_database_id,
        clock=clock,
        timeout_seconds=settings.mana_family_source_timeout_seconds,
    )
    reads = FamilySourceService(
        store,
        children,
        source,
        clock=clock,
        app_usage=ManakidsChildUsageSource(
            client,
            account_auth,
            base_url=settings.manakids_api_base_url,
            clock=clock,
            timeout_seconds=settings.mana_family_source_timeout_seconds,
        )
        if settings.mana_family_app_usage_enabled and account_auth is not None
        else None,
    )
    collection = None
    collection_store = None
    if settings.mana_family_collection_enabled:
        assert account_auth is not None
        registered: tuple[FamilySourceKey, ...] = (
            ("firebase.child_battery.v1", "manakids.child_app_usage.v1")
            if settings.mana_family_app_usage_enabled
            else ("firebase.child_battery.v1",)
        )
        collection_store = SqliteFamilyCollectionStore(
            settings.mana_family_collection_database_path,
            binding=f"mana:{settings.firebase_project_id}:{settings.firebase_database_id}:manakids-v1",
            policy=settings.mana_family_collection_policy,
            sources=registered,
        )
        await collection_store.initialize(clock())
        collection = FamilyCollectionService(
            collection_store,
            ManakidsFamilyInventory(
                client,
                account_auth,
                base_url=settings.manakids_api_base_url,
                clock=clock,
                timeout_seconds=settings.mana_parent_chat_source_timeout_seconds,
            ),
            reads,
            store,
            clock=clock,
        )
    return FamilySourceRuntime(reads, store, policy, collection, collection_store)
