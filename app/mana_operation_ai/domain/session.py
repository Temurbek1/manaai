"""Private conversation context; prior results never grant authority or fresh evidence."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.mana_operation_ai.domain.models import DomainModel
from app.mana_operation_ai.domain.workspace_actions import WorkspaceActionHistory
from app.mana_operation_ai.domain.workspace_retention_contacts import WorkspaceContactHistory


class SessionUserContext(DomainModel):
    kind: Literal["user_message", "prior_objective", "prior_criteria", "constraint", "instruction"]
    text: str = Field(max_length=6000)
    origin_id: str = Field(max_length=128)
    also_kinds: list[
        Literal["user_message", "prior_objective", "prior_criteria", "constraint", "instruction"]
    ] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_context_roles(self) -> "SessionUserContext":
        if self.kind in self.also_kinds or len(set(self.also_kinds)) != len(self.also_kinds):
            raise ValueError("Additional context roles must be distinct from the primary role")
        return self


class SessionEvidenceReference(DomainModel):
    report_id: str
    capability_key: str
    product: Literal["mana", "360rec"]
    collected_at: datetime | None
    fresh_until: datetime | None
    refresh_status: Literal["live", "cached", "stale", "unknown"]
    limitations: list[str] = Field(default_factory=list, max_length=10)
    shortened: bool = False


class SessionCheckpoint(DomainModel):
    goal_id: str
    status: Literal["completed", "cancelled"]
    updated_at: datetime
    result: str = Field(max_length=2000)
    result_shortened: bool = False
    sources: list[SessionEvidenceReference] = Field(default_factory=list, max_length=4)


class SessionMemory(DomainModel):
    topic_id: str
    product: Literal["mana", "360rec"]
    captured_at: datetime
    user_context: list[SessionUserContext] = Field(default_factory=list, max_length=400)
    checkpoints: list[SessionCheckpoint] = Field(default_factory=list, max_length=3)
    actions: list[WorkspaceActionHistory] = Field(default_factory=list, max_length=3)
    # Keep empty old memories byte-equivalent without erasing the typed API schema.
    retention_contacts: list[WorkspaceContactHistory] = Field(
        default_factory=list, max_length=3, exclude_if=lambda value: not value
    )
    older_checkpoints_omitted: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_action_scope(self) -> "SessionMemory":
        if (self.actions or self.retention_contacts) and self.product != "mana":
            raise ValueError("Sandbox MANA action history cannot enter another product context")
        if self.retention_contacts and self.captured_at.utcoffset() is None:
            raise ValueError("Contact context requires an aware frozen capture cutoff")
        if any(item.at >= self.captured_at for item in self.retention_contacts):
            raise ValueError("Contact history must precede its frozen capture cutoff")
        return self
