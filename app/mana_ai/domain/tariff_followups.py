"""Exact historical tariff context, never a current price or commercial grant."""

from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId
from app.mana_ai.domain.client_upsell import UpsellIntent, UpsellQuote


class TariffRequestMessage(ChatContract):
    turn_id: int = Field(gt=0, strict=True)
    request_id: UUID
    message: str = Field(min_length=1, max_length=2000)


class TariffFollowupContext(ChatContract):
    parent_id: ParentChatId
    turn_id: int = Field(gt=0, strict=True)
    captured_at: AwareDatetime
    origin_intent: UpsellIntent
    origin_messages: tuple[TariffRequestMessage, ...] = Field(min_length=1, max_length=2)
    quote: UpsellQuote
    delivered_turn_id: int = Field(gt=0, strict=True)
    delivered_request_id: UUID
    delivered_answer: str = Field(min_length=1, max_length=4000)
    delivered_at: AwareDatetime
    refinement_requests: tuple[TariffRequestMessage, ...] = Field(default=(), max_length=2)

    @model_validator(mode="after")
    def same_parent_and_prior_turn(self) -> "TariffFollowupContext":
        if (
            self.origin_intent.parent_id != self.parent_id
            or self.origin_intent.origin_turn_id > self.delivered_turn_id
            or self.delivered_turn_id >= self.turn_id
            or self.origin_messages[-1].turn_id != self.origin_intent.origin_turn_id
            or any(message.turn_id > self.delivered_turn_id for message in self.origin_messages)
            or self.origin_intent.created_at > self.delivered_at
            or self.quote.catalog_collected_at > self.delivered_at
            or self.delivered_at > self.captured_at
            or any(
                not self.delivered_turn_id < message.turn_id < self.turn_id
                for message in self.refinement_requests
            )
        ):
            raise ValueError("Tariff context must belong to one earlier delivered parent quote")
        if self.origin_intent.choice.parent_quote not in self.origin_messages[0].message:
            raise ValueError("The complete original tariff request must be preserved")
        return self

    def presentation(self) -> dict[str, object]:
        result: dict[str, object] = {
            "historical_context_not_current_prices_or_authority": True,
            "original_requests": [message.message for message in self.origin_messages],
            "previous_terms": self.origin_intent.choice.model_dump(mode="json"),
            "previous_quote": self.quote.model_dump(mode="json"),
            "quoted_at": self.delivered_at.isoformat(),
            "earlier_refinement_requests": [
                message.message for message in self.refinement_requests
            ],
        }
        if len(self.quote.options) == 1:
            prior = self.quote.options[0]
            ceiling = prior.price_minor - 1
            if self.origin_intent.choice.maximum_price_minor is not None:
                ceiling = min(ceiling, self.origin_intent.choice.maximum_price_minor)
            result["strictly_cheaper_reference"] = {
                "currency": prior.currency,
                "maximum_price_minor": ceiling,
                "positive_price_can_match": ceiling >= 1,
                "historical_reference_not_commercial_authority": True,
            }
        return result
