"""One model-free chat lab for the current compatible family workflows."""

from dataclasses import replace
from pathlib import Path

from app.mana_ai.application.ports import Clock
from app.services.mana_chat_lab import LabOptions


def workspace_options(
    directory: Path, *, clock: Clock | None = None, worker_enabled: bool = True
) -> LabOptions:
    options = LabOptions(
        directory,
        worker_enabled=worker_enabled,
        native_sources=True,
        native_observations=True,
        source_reviews=True,
        reminders=True,
        retention=True,
        upsell=True,
        tariff_context=True,
        expiry=True,
        manager=True,
        shared_conversion_profile=True,
        day_usage=True,
        dated_reviews=True,
        location=True,
        usage_comparisons=True,
        parallel_worker=True,
        safety_remainder=True,
        parent_support_questions=True,
        clarifications=True,
        upsell_currency=True,
        inline_upsell=True,
        expiry_fixture_days=30,
    )
    if clock is None:
        return options
    return replace(options, clock=clock)
