from types import SimpleNamespace
from typing import Any, cast

from openai import AsyncOpenAI
from openai.lib._parsing._completions import type_to_response_format_param

from app.core.config import Settings
from app.mana_ai.domain.enums import AnalysisVerdict, ManaAICapability
from app.mana_ai.domain.responses import ModelAnalysis
from app.services.openai_service import OpenAIService
from tests.mana_ai_fixtures import details_for


class FakeResponses:
    def __init__(self, output: ModelAnalysis) -> None:
        self.output = output
        self.kwargs: dict[str, Any] = {}

    async def parse(self, **kwargs: Any) -> SimpleNamespace:
        self.kwargs = kwargs
        return SimpleNamespace(
            id="resp_test",
            model="gpt-5.4-nano-2026-03-17",
            created_at=1_786_334_400.0,
            status="completed",
            output_parsed=self.output,
            usage=SimpleNamespace(
                input_tokens=120,
                input_tokens_details=SimpleNamespace(cached_tokens=20),
                output_tokens=80,
                output_tokens_details=SimpleNamespace(reasoning_tokens=10),
                total_tokens=200,
            ),
        )


class FakeModels:
    async def retrieve(self, model: str) -> SimpleNamespace:
        return SimpleNamespace(id=model, owned_by="system", created=1_786_334_400)


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses
        self.models = FakeModels()


async def test_structured_openai_call_uses_low_cost_privacy_controls() -> None:
    settings = Settings(_env_file=None, openai_api_key="test-openai-key")
    output = ModelAnalysis(
        verdict=AnalysisVerdict.NO_RISK_DETECTED,
        summary="No risk was detected in available signals.",
        details=details_for(ManaAICapability.PARENT_COPILOT),
    )
    responses = FakeResponses(output)
    service = OpenAIService(settings)
    service._client = cast(AsyncOpenAI, FakeClient(responses))

    result = await service.create_structured_response(
        text_format=ModelAnalysis,
        system_prompt="Analyze the payload.",
        user_input="{}",
        safety_identifier="mana_hashed_subject",
    )

    assert result is output
    assert responses.kwargs["model"] == "gpt-5.4-nano"
    assert responses.kwargs["reasoning"] == {"effort": "none"}
    assert responses.kwargs["text"] == {"verbosity": "low"}
    assert "verbosity" not in responses.kwargs
    assert responses.kwargs["max_output_tokens"] == 2_048
    assert responses.kwargs["safety_identifier"] == "mana_hashed_subject"
    assert responses.kwargs["store"] is False
    assert "temperature" not in responses.kwargs


async def test_structured_openai_call_exposes_non_secret_usage_metadata() -> None:
    settings = Settings(_env_file=None, openai_api_key="test-openai-key")
    output = ModelAnalysis(
        verdict=AnalysisVerdict.NO_RISK_DETECTED,
        summary="No risk was detected in available signals.",
        details=details_for(ManaAICapability.PARENT_COPILOT),
    )
    responses = FakeResponses(output)
    service = OpenAIService(settings)
    service._client = cast(AsyncOpenAI, FakeClient(responses))

    result = await service.create_structured_response_with_metadata(
        text_format=ModelAnalysis,
        system_prompt="Analyze the payload.",
        user_input="{}",
    )

    assert result.output is output
    assert result.metadata.response_id == "resp_test"
    assert result.metadata.input_tokens == 120
    assert result.metadata.cached_input_tokens == 20
    assert result.metadata.output_tokens == 80
    assert result.metadata.reasoning_output_tokens == 10
    assert result.metadata.total_tokens == 200


async def test_configured_model_access_exposes_non_secret_metadata() -> None:
    settings = Settings(_env_file=None, openai_api_key="test-openai-key")
    responses = FakeResponses(
        ModelAnalysis(
            verdict=AnalysisVerdict.NO_RISK_DETECTED,
            summary="No risk was detected in available signals.",
            details=details_for(ManaAICapability.PARENT_COPILOT),
        )
    )
    service = OpenAIService(settings)
    service._client = cast(AsyncOpenAI, FakeClient(responses))

    result = await service.retrieve_configured_model()

    assert result.model_id == "gpt-5.4-nano"
    assert result.owned_by == "system"
    assert result.created_at == 1_786_334_400


def test_model_schema_uses_only_json_schema_union_keywords() -> None:
    response_format = type_to_response_format_param(ModelAnalysis)
    serialized = str(response_format)

    assert "discriminator" not in serialized
    assert "oneOf" not in serialized
    assert "anyOf" in serialized
