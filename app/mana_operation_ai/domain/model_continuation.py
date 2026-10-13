"""Private provider-neutral continuation; never evidence, consent or an executable tool."""

import hashlib
from typing import Literal

from pydantic import Field, model_validator

from app.mana_operation_ai.domain.agent_tools import AgentToolCall
from app.mana_operation_ai.domain.models import DomainModel


class ModelContinuation(DomainModel):
    protocol: Literal["goal-model-continuation-v1", "goal-model-continuation-v2"] = (
        "goal-model-continuation-v1"
    )
    model: str = Field(min_length=1, max_length=100)
    scope_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload: str = Field(min_length=1, max_length=262144)
    payload_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    compactions: int = Field(default=0, ge=0, le=48)
    pending_tool_position: int | None = Field(default=None, ge=0, le=119)
    pending_tool_call: AgentToolCall | None = None

    @model_validator(mode="after")
    def validate_integrity(self) -> "ModelContinuation":
        if self.protocol == "goal-model-continuation-v1" and (
            self.pending_tool_position is not None and self.pending_tool_position > 11
        ):
            raise ValueError("The legacy continuation protocol remains limited to twelve tools")
        if hashlib.sha256(self.payload.encode()).hexdigest() != self.payload_digest:
            raise ValueError("Model continuation payload integrity mismatch")
        if (self.pending_tool_position is None) != (self.pending_tool_call is None):
            raise ValueError("A pending model tool requires its exact durable position")
        return self
