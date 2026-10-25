"""Parent-chat re-engagement; chat inactivity never proves application churn."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from app.mana_ai.domain.chat import ChatContract, ParentChatId, ParentChatRequest, ResponseLanguage


class ClientRetentionPolicy(ChatContract):
    inactive_chat_days: int = Field(default=14, ge=1, le=90, strict=True)
    daily_outreach_limit: int = Field(default=20, ge=1, le=100, strict=True)
    preparation_seconds: int = Field(default=180, ge=60, le=300, strict=True)


class RetentionIntent(ChatContract):
    intent_id: UUID
    parent_id: ParentChatId
    request_id: UUID
    anchor_turn_id: int = Field(gt=0, strict=True)
    last_parent_message_at: AwareDatetime
    admitted_at: AwareDatetime
    expires_at: AwareDatetime
    language: ResponseLanguage
    contact_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: Literal["chat_inactive"] = "chat_inactive"


class ParentTouchRetentionTurn(ParentChatRequest):
    """Host-only assistant message, not a fabricated parent text or child event."""

    message: Literal[""] = ""
    retention_intent_id: UUID
