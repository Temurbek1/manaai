"""Private provider-neutral continuation; never evidence, consent or an executable tool."""

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from app.mana_operation_ai.domain.agent_tools import AgentToolCall
from app.mana_operation_ai.domain.models import DomainModel

ContinuationProtocol = Literal[
    "goal-model-continuation-v1", "goal-model-continuation-v2", "goal-model-continuation-v3"
]


class RuntimeSnapshotRef(DomainModel):
    """Exact provenance of a runtime-owned input item, never inferred from provider text."""

    position: int = Field(ge=0, le=127, strict=True)
    item_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class ModelContinuation(DomainModel):
    protocol: ContinuationProtocol = "goal-model-continuation-v1"
    model: str = Field(min_length=1, max_length=100)
    scope_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload: str = Field(min_length=1, max_length=262144)
    payload_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    compactions: int = Field(default=0, ge=0, le=48)
    pending_tool_position: int | None = Field(default=None, ge=0, le=119)
    pending_tool_call: AgentToolCall | None = None
    runtime_snapshots: list[RuntimeSnapshotRef] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def validate_integrity(self) -> "ModelContinuation":
        if self.protocol != "goal-model-continuation-v3" and self.runtime_snapshots:
            raise ValueError("Runtime snapshot provenance requires continuation v3")
        positions = [item.position for item in self.runtime_snapshots]
        if positions != sorted(set(positions)):
            raise ValueError("Runtime snapshot positions must be unique and ordered")
        if self.protocol == "goal-model-continuation-v1" and (
            self.pending_tool_position is not None and self.pending_tool_position > 11
        ):
            raise ValueError("The legacy continuation protocol remains limited to twelve tools")
        if hashlib.sha256(self.payload.encode()).hexdigest() != self.payload_digest:
            raise ValueError("Model continuation payload integrity mismatch")
        if self.runtime_snapshots:
            values = json.loads(self.payload)
            if not isinstance(values, list):
                raise ValueError("Runtime snapshot provenance requires an item array")
            for ref in self.runtime_snapshots:
                if (
                    ref.position >= len(values)
                    or ref.item_digest
                    != hashlib.sha256(
                        json.dumps(
                            values[ref.position], ensure_ascii=False, sort_keys=True
                        ).encode()
                    ).hexdigest()
                ):
                    raise ValueError("Runtime snapshot provenance integrity mismatch")
        if (self.pending_tool_position is None) != (self.pending_tool_call is None):
            raise ValueError("A pending model tool requires its exact durable position")
        return self
