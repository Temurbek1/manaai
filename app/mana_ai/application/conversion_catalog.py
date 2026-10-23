"""Catalog evidence can reject a configured price, never approve an offer."""

from datetime import datetime
from typing import Literal, Protocol

from app.mana_ai.domain.conversion import PaidConversionOffer
from app.mana_ai.domain.conversion_catalog import ConversionCatalogObservation

CatalogPriceRejection = Literal[
    "catalog_not_current",
    "catalog_tariff_absent",
    "catalog_discount_unverified",
    "catalog_price_mismatch",
]


class ConversionCatalogSource(Protocol):
    async def read(self) -> ConversionCatalogObservation: ...


def catalog_price_rejection(
    offer: PaidConversionOffer,
    observation: ConversionCatalogObservation,
    *,
    now: datetime,
) -> CatalogPriceRejection | None:
    """Compare an ordinary tariff with separately owner-approved billing terms.

    None means only that the observed price/currency/duration match. It is not
    source freshness at delivery, a full offer approval or permission to contact.
    Callers must not substitute this evidence for the owning policy or invent the
    missing renewal/checkout terms. No production caller is enabled here.
    """
    if now.utcoffset() is None:
        raise ValueError("An aware comparison clock is required")
    # Revalidate immutable boundary models, including unchecked model_copy values.
    offer = PaidConversionOffer.model_validate(vars(offer))
    observation = ConversionCatalogObservation.model_validate(
        observation.model_dump(warnings=False)
    )
    age = (now - observation.collected_at).total_seconds()
    if age < 0 or age > 21600:
        return "catalog_not_current"
    tariff = next(
        (item for item in observation.tariffs if item.tariff_id == offer.billing_offer_id), None
    )
    if tariff is None:
        return "catalog_tariff_absent"
    if offer.discount_percent or offer.list_price_minor != offer.price_minor:
        return "catalog_discount_unverified"
    if (offer.price_minor, offer.currency, offer.duration_days) != (
        tariff.price_minor,
        tariff.currency,
        tariff.duration_days,
    ):
        return "catalog_price_mismatch"
    return None
