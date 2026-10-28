"""Literal changes to an already confirmed parent tariff enquiry, not model decisions."""

from typing import Literal

from pydantic import Field, model_validator

from app.mana_ai.domain.chat import ChatContract, ResponseLanguage
from app.mana_ai.domain.client_upsell import UpsellIntent
from app.mana_ai.domain.tariff_followups import TariffFollowupContext


class LiteralTariffChange(ChatContract):
    kind: Literal["duration_days", "maximum_total", "currency"]
    exact_message: str = Field(min_length=1, max_length=2000)
    language: ResponseLanguage | None
    duration_days: int | None = Field(default=None, ge=1, le=366, strict=True)
    maximum_price_minor: int | None = Field(default=None, ge=1, le=10**14, strict=True)
    currency: Literal["UZS", "USD"] | None = None

    @model_validator(mode="after")
    def exact_change(self) -> "LiteralTariffChange":
        if (
            self.kind == "duration_days"
            and (
                self.duration_days is None or self.maximum_price_minor is not None or self.currency
            )
            or self.kind == "maximum_total"
            and (self.maximum_price_minor is None or self.duration_days is not None)
            or self.kind == "currency"
            and (
                self.currency is None
                or self.duration_days is not None
                or self.maximum_price_minor is not None
            )
        ):
            raise ValueError("A literal command changes only its declared tariff term")
        return self


class LiteralTariffDerivation(ChatContract):
    context: TariffFollowupContext
    change: LiteralTariffChange
    intent: UpsellIntent

    @model_validator(mode="after")
    def same_parent_and_origin(self) -> "LiteralTariffDerivation":
        if (
            self.context.parent_id != self.intent.parent_id
            or self.context.turn_id != self.intent.origin_turn_id
            or self.intent.choice.parent_quote != self.change.exact_message
            or self.context.captured_at != self.intent.created_at
        ):
            raise ValueError("A literal change belongs to its own new parent tariff turn")
        return self
