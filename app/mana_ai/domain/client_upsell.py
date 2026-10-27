"""Explicit parent tariff enquiries, not entitlement changes or commercial consent."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId, ResponseLanguage
from app.mana_ai.domain.conversion_catalog import (
    ConversionCatalogObservation,
    ConversionTariffPrice,
)

TARIFF_CANCEL_COMMANDS = frozenset(
    {"отмени подбор", "tarif tanlashni bekor qiling", "cancel tariff request"}
)


class ClientUpsellPolicy(ChatContract):
    catalog_cooldown_seconds: int = Field(default=21600, ge=21600, le=86400, strict=True)
    catalog_reads_per_24h: int = Field(default=4, ge=1, le=4, strict=True)
    maximum_pending_global: int = Field(default=100, ge=1, le=1000, strict=True)
    maximum_pending_per_parent: int = Field(default=3, ge=1, le=10, strict=True)
    claim_seconds: int = Field(default=180, ge=60, le=300, strict=True)


class UpsellChoice(ChatContract):
    parent_quote: str = Field(min_length=1, max_length=250, pattern=r"\S")
    objective: Literal["lowest_total", "lowest_daily", "list"]
    currency: Literal["UZS", "USD"]
    minimum_days: int = Field(ge=1, le=366, strict=True)
    maximum_days: int = Field(ge=1, le=366, strict=True)
    maximum_price_minor: int | None = Field(ge=1, le=10**14, strict=True)

    @model_validator(mode="after")
    def ordered_days(self) -> "UpsellChoice":
        if self.minimum_days > self.maximum_days:
            raise ValueError("Tariff duration range must be ordered")
        return self


class UpsellScope(ChatContract):
    protocol: Literal["catalog-enquiry-v1", "catalog-currency-v2"] = "catalog-enquiry-v1"
    maximum_days: Literal[366] = 366
    currency_unit: Literal["one_currency_unit_is_100_minor_units"] = (
        "one_currency_unit_is_100_minor_units"
    )


class UpsellEnquiry(ChatContract):
    """New captured protocol: missing currency is a question, never a default."""

    parent_quote: str = Field(min_length=1, max_length=250, pattern=r"\S")
    objective: Literal["lowest_total", "lowest_daily", "list"]
    currency: Literal["UZS", "USD"] | None
    minimum_days: int = Field(ge=1, le=366, strict=True)
    maximum_days: int = Field(ge=1, le=366, strict=True)
    maximum_price_minor: int | None = Field(ge=1, le=10**14, strict=True)

    @model_validator(mode="after")
    def ordered_days(self) -> "UpsellEnquiry":
        if self.minimum_days > self.maximum_days:
            raise ValueError("Tariff duration range must be ordered")
        return self


class UpsellIntent(ChatContract):
    intent_id: UUID
    parent_id: ParentChatId
    origin_turn_id: int = Field(gt=0, strict=True)
    choice: UpsellChoice
    language: ResponseLanguage
    created_at: AwareDatetime


class UpsellWork(ChatContract):
    intent: UpsellIntent
    claim_id: UUID
    expires_at: AwareDatetime


class CatalogReadClaim(ChatContract):
    claim_id: UUID
    expires_at: AwareDatetime


class UpsellQuote(ChatContract):
    catalog_collected_at: AwareDatetime
    options: tuple[ConversionTariffPrice, ...] = Field(max_length=3)
    objective: Literal["lowest_total", "lowest_daily", "list"]
    coverage: Literal["bounded_catalog_page"] = "bounded_catalog_page"
    recipient_eligibility: Literal["not_verified"] = "not_verified"
    creates_payment: Literal[False] = False


class CatalogAdmission(ChatContract):
    snapshot: ConversionCatalogObservation | None = None
    claim: CatalogReadClaim | None = None
    waiting_for: CatalogReadClaim | None = None
    refusal: Literal["blocked", "busy", "cooldown", "daily_limit"] | None = None

    @model_validator(mode="after")
    def one_outcome(self) -> "CatalogAdmission":
        if sum(value is not None for value in (self.snapshot, self.claim, self.refusal)) != 1:
            raise ValueError("Exactly one catalog admission outcome is required")
        if self.waiting_for is not None and self.refusal != "busy":
            raise ValueError("Only an existing busy claim may be observed")
        return self


class CatalogReadObservation(ChatContract):
    """An existing public-price receipt, never a new provider-read admission."""

    status: Literal["reading", "recorded", "unknown"]
    snapshot: ConversionCatalogObservation | None = None

    @model_validator(mode="after")
    def recorded_snapshot(self) -> "CatalogReadObservation":
        if (self.status == "recorded") != (self.snapshot is not None):
            raise ValueError("Only a recorded catalog receipt contains a snapshot")
        return self
