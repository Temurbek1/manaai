from datetime import datetime
from typing import Protocol

from app.mana_ai.domain.requests import ManaAIRequest
from app.mana_ai.domain.responses import CheckResult, FindingDraft, ModelAnalysis


class ModelGatewayError(RuntimeError):
    """The semantic model could not complete an analysis."""


class ManaAIModelGateway(Protocol):
    @property
    def model_name(self) -> str: ...

    async def analyze(
        self,
        request: ManaAIRequest,
        *,
        deterministic_findings: list[FindingDraft],
        required_checks: list[CheckResult],
    ) -> ModelAnalysis: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
