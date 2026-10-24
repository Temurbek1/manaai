"""Explicit source wiring; construction performs no Google/provider reads."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.core.config import Settings
from app.mana_ai.application.chat_ports import ParentChildrenSource
from app.mana_ai.application.family_sources import FamilySourceService
from app.mana_ai.domain.source_safety import SourceSafetyPolicy
from app.services.family_google_auth import FamilyFirestoreToken
from app.services.firestore_child_battery import FirestoreChildBatterySource
from app.services.source_safety_store import SqliteSourceSafetyStore


@dataclass(frozen=True)
class FamilySourceRuntime:
    reads: FamilySourceService
    store: SqliteSourceSafetyStore
    safety_policy: SourceSafetyPolicy


async def family_source_runtime(
    settings: Settings,
    client: httpx.AsyncClient,
    children: ParentChildrenSource,
    *,
    clock: Callable[[], datetime],
) -> FamilySourceRuntime | None:
    if not settings.mana_family_sources_enabled:
        return None
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
    store = SqliteSourceSafetyStore(
        settings.mana_family_source_database_path,
        binding=(
            f"mana:firebase:{settings.firebase_project_id}:"
            f"{settings.firebase_database_id}:child-battery-v1"
        ),
        limits=settings.mana_family_source_limits,
        policy=policy,
        enabled=settings.mana_family_source_safety_enabled,
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
    return FamilySourceRuntime(
        FamilySourceService(store, children, source, clock=clock), store, policy
    )
