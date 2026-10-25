"""Minimized selected-tariff facts from a bounded, known inventory page."""

from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.mana_ai.domain.chat import ChatContract
from app.mana_ai.domain.family_collection import FamilyInventoryPage
from app.mana_ai.domain.retention_expiry import RetentionTariffFact


class InventoryTariffPolicy(ChatContract):
    maximum_batches: int = Field(default=10000, ge=1, le=1000000, strict=True)
    maximum_age_seconds: int = Field(default=180, ge=30, le=180, strict=True)
    claim_seconds: int = Field(default=30, ge=5, le=120, strict=True)


class TariffInventoryPage(FamilyInventoryPage):
    tariff_facts: tuple[RetentionTariffFact, ...] = Field(max_length=100)

    @model_validator(mode="after")
    def exact_inventory_scope(self) -> "TariffInventoryPage":
        if tuple(f.parent_id for f in self.tariff_facts) != tuple(
            f.parent_id for f in self.families
        ) or any(f.collected_at != self.collected_at for f in self.tariff_facts):
            raise ValueError("Tariff facts must match the exact inventory page and collection")
        return self


class InventoryTariffWork(ChatContract):
    page_id: int = Field(gt=0, strict=True)
    window_id: UUID
    claim_id: UUID
    page_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    facts_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    facts: tuple[RetentionTariffFact, ...] = Field(min_length=1, max_length=100)
    expires_at: AwareDatetime
