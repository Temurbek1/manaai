"""Verified parent-child linkage observations, never online status or contact grants."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId, ResponseLanguage

SetupChildId = Annotated[int, Field(gt=0, le=2**63 - 1, strict=True)]


class ParentSetupFact(ChatContract):
    source: Literal["complete_manakids_parent_children"] = "complete_manakids_parent_children"
    parent_id: ParentChatId
    collected_at: AwareDatetime
    connected_child_ids: tuple[SetupChildId, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def canonical_children(self) -> "ParentSetupFact":
        if (
            int(self.parent_id) > 2**63 - 1
            or any(
                type(child) is not int or not 0 < child <= 2**63 - 1
                for child in self.connected_child_ids
            )
            or tuple(sorted(set(self.connected_child_ids))) != self.connected_child_ids
        ):
            raise ValueError("Setup evidence needs exact canonical parent-child linkage")
        return self


class ParentSetupPolicy(ChatContract):
    maximum_age_seconds: int = Field(default=180, ge=30, le=180, strict=True)
    maximum_profiles: int = Field(default=10000, ge=1, le=300000, strict=True)
    maximum_epochs: int = Field(default=50000, ge=1, le=1000000, strict=True)
    question_validity_seconds: int = Field(default=86400, ge=60, le=86400, strict=True)
    cooldown_days: int = Field(default=7, ge=7, le=90, strict=True)
    daily_global_limit: int = Field(default=20, ge=1, le=100, strict=True)
    maximum_batches: int = Field(default=10000, ge=1, le=100000, strict=True)
    batch_claim_seconds: int = Field(default=120, ge=30, le=180, strict=True)


class ParentSetupNotice(ChatContract):
    origin: Literal["profile_child_link_setup_v1"] = "profile_child_link_setup_v1"
    parent_id: ParentChatId
    epoch_id: UUID
    question_id: UUID
    text: str = Field(min_length=1, max_length=2000, strict=True)
    question: str = Field(min_length=1, max_length=400, strict=True)
    source_fact: ParentSetupFact
    contact: str = Field(pattern=r"^[a-f0-9]{64}$", strict=True)
    language: ResponseLanguage
    timezone: str = Field(min_length=1, max_length=64, strict=True)

    @model_validator(mode="after")
    def own_empty_profile(self) -> "ParentSetupNotice":
        if (
            self.source_fact.parent_id != self.parent_id
            or self.source_fact.connected_child_ids
            or not self.text.endswith(self.question)
        ):
            raise ValueError("A setup notice retains its exact own-parent empty profile")
        return self


class ParentSetupBatch(ChatContract):
    facts: tuple[ParentSetupFact, ...] = Field(max_length=100)
    unknown_parent_ids: tuple[ParentChatId, ...] = Field(max_length=100)
    collected_at: AwareDatetime

    @model_validator(mode="after")
    def one_complete_page(self) -> "ParentSetupBatch":
        ids = tuple(f.parent_id for f in self.facts) + self.unknown_parent_ids
        if (
            not 1 <= len(ids) <= 100
            or len(set(ids)) != len(ids)
            or any(f.collected_at != self.collected_at for f in self.facts)
        ):
            raise ValueError("Setup fan-out requires one exact dated bounded page")
        return self


class SetupInventoryWork(ParentSetupBatch):
    page_id: int = Field(gt=0, strict=True)
    window_id: UUID
    claim_id: UUID
    deadline: AwareDatetime


def setup_observation_current(
    fact: ParentSetupFact, now: datetime, policy: ParentSetupPolicy
) -> bool:
    return 0 <= (now - fact.collected_at).total_seconds() <= policy.maximum_age_seconds
