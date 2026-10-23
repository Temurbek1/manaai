"""Observed tariff prices, not approved offers, checkout or contact authority."""

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from app.mana_ai.domain.chat import ChatContract


class ConversionTariffPrice(ChatContract):
    tariff_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$", strict=True)
    currency: Literal["UZS", "USD"]
    price_minor: int = Field(gt=0, strict=True)
    duration_days: int = Field(ge=1, le=366, strict=True)


class ConversionCatalogObservation(ChatContract):
    """One bounded page; no claim that every billable tariff is represented.

    Provider descriptions, old prices and monthly flags cannot supply discount,
    renewal, checkout, recipient eligibility or approval terms.
    """

    source: Literal["manakids_tariffs"] = "manakids_tariffs"
    collected_at: AwareDatetime
    tariffs: tuple[ConversionTariffPrice, ...] = Field(max_length=25)

    @model_validator(mode="after")
    def unique_tariffs(self) -> "ConversionCatalogObservation":
        if len({item.tariff_id for item in self.tariffs}) != len(self.tariffs):
            raise ValueError("Catalog tariff identifiers must be unique")
        return self
