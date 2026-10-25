"""Native source model transport ports; dispatch and durable metering stay host-owned."""

from dataclasses import dataclass
from typing import Literal, Protocol

from app.mana_ai.application.chat_ports import ChatPrompt
from app.mana_ai.domain.chat import ChatTokens
from app.mana_ai.domain.family_day_usage import DayUsageReceipt
from app.mana_ai.domain.family_sources import FamilySourceReceipt
from app.mana_ai.domain.source_tools import (
    SourceToolContinuation,
    SourceToolModelProfile,
    SourceToolScope,
)


@dataclass(frozen=True)
class SourceToolPrompt:
    input: ChatPrompt
    scope: SourceToolScope
    continuation: SourceToolContinuation | None = None
    source_result: FamilySourceReceipt | DayUsageReceipt | None = None


@dataclass(frozen=True)
class SourceModelReceipt:
    usage: ChatTokens
    model: str
    completed: bool
    answer: str | None = None
    continuation: SourceToolContinuation | None = None
    failure_code: Literal["source_model_output_invalid"] | None = None


class SourceToolModel(Protocol):
    @property
    def source_profile(self) -> SourceToolModelProfile: ...

    @property
    def model_name(self) -> str: ...

    def source_input_digest(self, prompt: SourceToolPrompt) -> str: ...

    async def count_source_input(self, prompt: SourceToolPrompt) -> int: ...

    async def respond_source(
        self, prompt: SourceToolPrompt, *, max_output_tokens: int
    ) -> SourceModelReceipt: ...
