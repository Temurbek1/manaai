"""Private conversation context; prior results never grant authority or fresh evidence."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.mana_operation_ai.domain.models import DomainModel
from app.mana_operation_ai.domain.workspace_actions import WorkspaceActionHistory


class SessionUserContext(DomainModel):
    kind: Literal["user_message", "prior_objective", "prior_criteria", "constraint", "instruction"]
    text: str = Field(max_length=6000)
    origin_id: str = Field(max_length=128)


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
    older_checkpoints_omitted: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_action_scope(self) -> "SessionMemory":
        if self.actions and self.product != "mana":
            raise ValueError("Sandbox MANA action history cannot enter another product context")
        return self
