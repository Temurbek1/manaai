"""Explicit source wiring; construction performs no Google/provider reads."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from app.core.config import Settings
from app.mana_ai.application.chat_ports import ParentChildrenSource
from app.mana_ai.application.dated_collection import DatedCollectionService
from app.mana_ai.application.day_usage_service import FamilyDayUsageService
from app.mana_ai.application.family_collection import FamilyCollectionService
from app.mana_ai.application.family_day_usage import ParentUsageIdentitySource
from app.mana_ai.application.family_sources import FamilySourceService
from app.mana_ai.application.inventory_tariffs import InventoryTariffSink, TariffCollectionService
from app.mana_ai.domain.family_sources import FamilySourceKey
from app.mana_ai.domain.source_safety import SourceSafetyPolicy
from app.services.dated_collection_store import SqliteDatedCollectionStore
from app.services.day_review_cache import SqliteDayReviewCache
from app.services.day_usage_cache import SqliteDayUsageCache
from app.services.family_collection_store import (
    SqliteFamilyCollectionStore,
    collection_storage_version,
)
from app.services.family_google_auth import FamilyFirestoreToken
from app.services.firestore_child_battery import FirestoreChildBatterySource
from app.services.firestore_child_location import FirestoreChildLocationSource
from app.services.inventory_tariff_store import SqliteInventoryTariffStore
from app.services.location_collection_store import SqliteLocationCollectionStore
from app.services.location_source_cache import SqliteLocationSourceCache
from app.services.manakids_child_usage import ManakidsChildUsageSource, ManakidsReadToken
from app.services.manakids_family_day_usage import ManakidsFamilyDayUsageSource
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
    day_usage: FamilyDayUsageService | None = None


async def family_source_runtime(
    settings: Settings,
    client: httpx.AsyncClient,
    children: ParentChildrenSource,
    *,
    clock: Callable[[], datetime],
    account_auth: ManakidsReadToken | None = None,
    tariff_receiver: InventoryTariffSink | None = None,
    day_identities: ParentUsageIdentitySource | None = None,
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
    source_version = await collection_storage_version(settings.mana_family_source_database_path)
    location_reader = settings.mana_family_location_enabled or source_version == 7
    day_review_reader = (
        settings.mana_family_day_reviews_enabled or source_version in {6, 7} or location_reader
    )
    day_reader = settings.mana_family_day_usage_enabled or source_version in {5, 6, 7}
    store = (
        (
            SqliteLocationSourceCache
            if location_reader
            else SqliteDayReviewCache
            if day_review_reader
            else SqliteDayUsageCache
            if day_reader
            else SqliteSourceReviewCache
        )(
            settings.mana_family_source_database_path,
            binding=(
                f"mana:firebase:{settings.firebase_project_id}:"
                f"{settings.firebase_database_id}:child-battery-v1"
            ),
            limits=settings.mana_family_source_limits,
            policy=policy,
            enabled=settings.mana_family_source_safety_enabled
            and settings.mana_family_source_reviews_enabled,
            review_policy=settings.mana_family_source_review_policy,
            **(
                {"location_enabled": settings.mana_family_location_enabled}
                if location_reader
                else {}
            ),
            **(
                {"dated_reviews_enabled": settings.mana_family_day_reviews_enabled}
                if day_review_reader
                else {}
            ),
        )
        if settings.mana_family_source_reviews_enabled or day_reader
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
        location=FirestoreChildLocationSource(
            client,
            auth,
            project_id=settings.firebase_project_id,
            database_id=settings.firebase_database_id,
            clock=clock,
            timeout_seconds=settings.mana_family_source_timeout_seconds,
        )
        if settings.mana_family_location_enabled
        else None,
    )
    day_usage = None
    if settings.mana_family_day_usage_enabled:
        if (
            day_identities is None
            or account_auth is None
            or not isinstance(store, SqliteDayUsageCache)
        ):
            raise ValueError(
                "Dated usage requires verified identity, shared authentication and its "
                "durable cache"
            )
        day_usage = FamilyDayUsageService(
            store,
            day_identities,
            ManakidsFamilyDayUsageSource(
                client,
                account_auth,
                day_identities,
                base_url=settings.manakids_api_base_url,
                clock=clock,
            ),
            clock=clock,
        )
    collection = None
    collection_store = None
    if settings.mana_family_collection_enabled:
        assert account_auth is not None
        if settings.mana_collection_tariffs_enabled and tariff_receiver is None:
            raise ValueError("Inventory tariff collection requires its owning receiver")
        registered: tuple[FamilySourceKey, ...] = (
            ("firebase.child_battery.v1", "manakids.child_app_usage.v1")
            if settings.mana_family_app_usage_enabled
            else ("firebase.child_battery.v1",)
        )
        collection_version = await collection_storage_version(
            settings.mana_family_collection_database_path
        )
        location_collection = settings.mana_family_location_enabled or collection_version == 4
        dated_reader = (
            settings.mana_collection_day_usage_enabled
            or collection_version in {3, 4}
            or location_collection
        )
        tariff_reader = (
            settings.mana_collection_tariffs_enabled or collection_version in {2, 3} or dated_reader
        )
        collection_binding = (
            f"mana:{settings.firebase_project_id}:{settings.firebase_database_id}:manakids-v1"
        )
        dated_options: dict[str, Any] = (
            {
                "dated_enabled": settings.mana_collection_day_usage_enabled,
                "source_binding": str(settings.mana_family_source_database_path.resolve()),
            }
            if dated_reader
            else {}
        )
        location_options: dict[str, Any] = (
            {"location_enabled": settings.mana_family_location_enabled}
            if location_collection
            else {}
        )
        collection_store = (
            (
                SqliteLocationCollectionStore
                if location_collection
                else SqliteDatedCollectionStore
                if dated_reader
                else SqliteInventoryTariffStore
            )(
                settings.mana_family_collection_database_path,
                tariff_policy=settings.mana_collection_tariff_policy,
                tariffs_enabled=settings.mana_collection_tariffs_enabled,
                recipient_binding=str(settings.mana_parent_chat_database_path.resolve()),
                binding=collection_binding,
                policy=settings.mana_family_collection_policy,
                sources=registered,
                **location_options,
                **dated_options,
            )
            if tariff_reader
            else SqliteFamilyCollectionStore(
                settings.mana_family_collection_database_path,
                binding=collection_binding,
                policy=settings.mana_family_collection_policy,
                sources=registered,
            )
        )
        await collection_store.initialize(clock())
        inventory = ManakidsFamilyInventory(
            client,
            account_auth,
            base_url=settings.manakids_api_base_url,
            clock=clock,
            timeout_seconds=settings.mana_parent_chat_source_timeout_seconds,
            include_tariffs=settings.mana_collection_tariffs_enabled,
        )
        collection = (
            DatedCollectionService(
                store=collection_store,
                inventory=inventory,
                sources=reads,
                observations=store,
                receiver=tariff_receiver if settings.mana_collection_tariffs_enabled else None,
                clock=clock,
                day_usage=day_usage if settings.mana_collection_day_usage_enabled else None,
                day_observations=store,
            )
            if isinstance(collection_store, SqliteDatedCollectionStore)
            and isinstance(store, SqliteDayUsageCache)
            else TariffCollectionService(
                collection_store,
                inventory,
                reads,
                store,
                receiver=tariff_receiver if settings.mana_collection_tariffs_enabled else None,
                clock=clock,
            )
            if isinstance(collection_store, SqliteInventoryTariffStore)
            else FamilyCollectionService(
                collection_store,
                inventory,
                reads,
                store,
                clock=clock,
            )
        )
    return FamilySourceRuntime(reads, store, policy, collection, collection_store, day_usage)
