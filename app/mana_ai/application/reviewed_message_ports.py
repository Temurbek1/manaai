from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.mana_ai.domain.family_agents import (
    ParentTouchReviewedTurn,
    ParentTouchReviewGuidance,
    ReviewedMessage,
)


class ReviewedMessageStore(Protocol):
    async def admit_reviewed(
        self, request: ParentTouchReviewedTurn, now: datetime, *, allow_new: bool
    ) -> ReviewedMessage: ...

    async def reviewed_message(
        self, parent_id: str, request_id: UUID, now: datetime
    ) -> ReviewedMessage: ...

    async def claim_reviewed_response(
        self, now: datetime
    ) -> tuple[ReviewedMessage, ParentTouchReviewedTurn] | None: ...

    async def review_guidance(
        self, parent_id: str, turn_id: int, connected: tuple[int, ...]
    ) -> ParentTouchReviewGuidance: ...
