import hashlib
import json
from datetime import UTC, datetime

from app.mana_ai.application.ports import ModelGatewayError
from app.mana_ai.domain.requests import ManaAIRequest
from app.mana_ai.domain.responses import CheckResult, FindingDraft, ModelAnalysis
from app.services.mana_ai_prompts import build_system_instructions
from app.services.mana_ai_provider_payload import build_provider_payload
from app.services.openai_service import AIConfigurationError, AIProviderError, OpenAIService


class ManaAIOpenAIModelGateway:
    def __init__(self, openai_service: OpenAIService) -> None:
        self._openai_service = openai_service

    @property
    def model_name(self) -> str:
        return self._openai_service.model_name

    async def analyze(
        self,
        request: ManaAIRequest,
        *,
        deterministic_findings: list[FindingDraft],
        required_checks: list[CheckResult],
    ) -> ModelAnalysis:
        payload = build_provider_payload(
            request,
            deterministic_findings=deterministic_findings,
            required_checks=required_checks,
        )
        try:
            return await self._openai_service.create_structured_response(
                text_format=ModelAnalysis,
                system_prompt=build_system_instructions(request.input.capability),
                user_input=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                safety_identifier=build_safety_identifier(request.subject.subject_id),
            )
        except (AIConfigurationError, AIProviderError) as exc:
            raise ModelGatewayError("MANA AI semantic analysis is unavailable") from exc


class SystemManaAIClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def build_safety_identifier(subject_id: str) -> str:
    digest = hashlib.sha256(subject_id.encode()).hexdigest()
    return f"mana_{digest[:59]}"
