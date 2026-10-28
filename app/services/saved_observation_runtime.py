"""Construct a credential-free saved-only reader under current source allowlists."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from app.mana_ai.application.chat_ports import ParentChildrenSource
from app.mana_ai.application.saved_observations import SavedObservationService
from app.mana_ai.domain.family_sources import FamilySourceLimits, ObservedSourceKey
from app.services.saved_observation_reader import SqliteSavedObservationReader


def saved_observation_service(
    *,
    path: Path,
    binding: str,
    source_limits: FamilySourceLimits,
    children: ParentChildrenSource,
    clock: Callable[[], datetime],
    maximum_age_seconds: int,
    app_usage: bool,
    location: bool,
    day_usage: bool,
) -> SavedObservationService:
    sources: list[ObservedSourceKey] = ["firebase.child_battery.v1"]
    if app_usage:
        sources.append("manakids.child_app_usage.v1")
    if location:
        sources.append("firebase.child_location.v1")
    if day_usage:
        sources.append("manakids.family_day_app_usage.v1")
    return SavedObservationService(
        SqliteSavedObservationReader(
            path.absolute(),
            binding=binding,
            limits=source_limits,
            allowed_sources=tuple(sources),
            maximum_age_seconds=maximum_age_seconds,
        ),
        children,
        clock=clock,
    )
