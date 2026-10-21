"""Minimized push requests and queue receipts, never delivery confirmations."""

from typing import Literal

from pydantic import Field, field_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId


class ParentPushMessage(ChatContract):
    parent_id: ParentChatId
    title: str = Field(min_length=1, max_length=120, pattern=r"\S", strict=True)
    description: str = Field(min_length=1, max_length=500, pattern=r"\S", strict=True)

    @field_validator("parent_id")
    @classmethod
    def bounded_profile_id(cls, value: str) -> str:
        if int(value) > 2**63 - 1:
            raise ValueError("A canonical profile parent ID is required")
        return value


class ParentPushReceipt(ChatContract):
    status: Literal["queued"] = "queued"
    queued_devices: int = Field(ge=0, strict=True)
