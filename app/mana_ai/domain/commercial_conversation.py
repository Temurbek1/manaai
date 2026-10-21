"""Frozen commercial observations, not model permissions or billing commands."""

from pydantic import AwareDatetime, Field

from app.mana_ai.domain.chat import ChatContract, ParentChatId, ResponseLanguage
from app.mana_ai.domain.conversion import ConversionProposal
from app.mana_ai.domain.conversion_grants import TrialGrantState


class CommercialConversationContext(ChatContract):
    parent_id: ParentChatId
    turn_id: int = Field(gt=0, strict=True)
    captured_at: AwareDatetime
    proposal: ConversionProposal | None
    offer_available_at_capture: bool
    grant: TrialGrantState | None
    grant_recorded_at: AwareDatetime | None
    language: ResponseLanguage | None

    def presentation(self) -> dict[str, object]:
        """Keep routing, purchase IDs and approval references out of inference."""
        offer = self.proposal.offer if self.proposal else None
        return {
            "captured_at": self.captured_at.isoformat(),
            "historical_context_not_action_authority": True,
            "offer_status": self.proposal.status if self.proposal else None,
            "offered_at": self.proposal.published_at.isoformat()
            if self.proposal and self.proposal.published_at
            else None,
            "offer_available_at_capture": self.offer_available_at_capture,
            "terms": offer.model_dump(
                mode="json",
                exclude={
                    "offer_id",
                    "billing_offer_id",
                    "approval_reference",
                    "priority",
                },
            )
            if offer
            else None,
            "free_days_action": {
                "status": self.grant.status,
                "days": self.grant.days,
                "recorded_at": self.grant_recorded_at.isoformat()
                if self.grant_recorded_at
                else None,
                "valid_until": self.grant.result.valid_until.isoformat()
                if self.grant.result
                else None,
            }
            if self.grant
            else None,
        }
