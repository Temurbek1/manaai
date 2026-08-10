from dataclasses import dataclass
from typing import TypeVar

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
)
from pydantic import BaseModel

from app.core.config import Settings
from app.schemas.ai import ChatRequest, ChatResponse, SummarizeRequest, SummarizeResponse

StructuredResponseT = TypeVar("StructuredResponseT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ModelAccessMetadata:
    model_id: str
    owned_by: str
    created_at: int


@dataclass(frozen=True, slots=True)
class StructuredResponseMetadata:
    response_id: str
    model: str
    created_at: float
    status: str | None
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    reasoning_output_tokens: int | None
    total_tokens: int | None


@dataclass(frozen=True, slots=True)
class StructuredResponseResult[ResponseT: BaseModel]:
    output: ResponseT
    metadata: StructuredResponseMetadata


class AIProviderError(RuntimeError):
    """Raised when the upstream AI provider cannot serve a request."""


class AIConfigurationError(AIProviderError):
    """Raised when the upstream AI provider credentials are not configured."""


class OpenAIService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.openai_timeout_seconds,
        )

    @property
    def model_name(self) -> str:
        return self._settings.openai_model

    async def retrieve_configured_model(self) -> ModelAccessMetadata:
        self._ensure_configured()
        try:
            model = await self._client.models.retrieve(self._settings.openai_model)
        except (
            APIConnectionError,
            APITimeoutError,
            APIStatusError,
        ) as exc:
            raise AIProviderError("OpenAI API request failed") from exc
        return ModelAccessMetadata(
            model_id=model.id,
            owned_by=model.owned_by,
            created_at=model.created,
        )

    async def chat(self, request: ChatRequest) -> ChatResponse:
        system_prompt = request.system_prompt or (
            "You are a concise assistant for an application API. "
            "Return direct, useful answers without hidden reasoning."
        )
        answer = await self._create_text_response(
            system_prompt=system_prompt,
            user_input=request.message,
        )
        return ChatResponse(answer=answer, model=self._settings.openai_model)

    async def summarize(self, request: SummarizeRequest) -> SummarizeResponse:
        answer = await self._create_text_response(
            system_prompt=(
                "Summarize the user text in no more than "
                f"{request.max_sentences} sentences. Keep key facts and remove filler."
            ),
            user_input=request.text,
        )
        return SummarizeResponse(summary=answer, model=self._settings.openai_model)

    async def create_structured_response(
        self,
        *,
        text_format: type[StructuredResponseT],
        system_prompt: str,
        user_input: str,
        safety_identifier: str | None = None,
    ) -> StructuredResponseT:
        result = await self.create_structured_response_with_metadata(
            text_format=text_format,
            system_prompt=system_prompt,
            user_input=user_input,
            safety_identifier=safety_identifier,
        )
        return result.output

    async def create_structured_response_with_metadata(
        self,
        *,
        text_format: type[StructuredResponseT],
        system_prompt: str,
        user_input: str,
        safety_identifier: str | None = None,
    ) -> StructuredResponseResult[StructuredResponseT]:
        self._ensure_configured()
        try:
            response = await self._client.responses.parse(
                model=self._settings.openai_model,
                instructions=system_prompt,
                input=user_input,
                max_output_tokens=self._settings.openai_max_output_tokens,
                reasoning={"effort": self._settings.openai_reasoning_effort},
                safety_identifier=safety_identifier,
                text_format=text_format,
                store=False,
                text={"verbosity": self._settings.openai_verbosity},
            )
        except (
            APIConnectionError,
            APITimeoutError,
            APIStatusError,
            ContentFilterFinishReasonError,
            LengthFinishReasonError,
        ) as exc:
            raise AIProviderError("OpenAI API request failed") from exc

        if response.output_parsed is None:
            raise AIProviderError("OpenAI API returned an empty structured response")
        usage = response.usage
        return StructuredResponseResult(
            output=response.output_parsed,
            metadata=StructuredResponseMetadata(
                response_id=response.id,
                model=response.model,
                created_at=response.created_at,
                status=response.status,
                input_tokens=usage.input_tokens if usage is not None else None,
                cached_input_tokens=(
                    usage.input_tokens_details.cached_tokens if usage is not None else None
                ),
                output_tokens=usage.output_tokens if usage is not None else None,
                reasoning_output_tokens=(
                    usage.output_tokens_details.reasoning_tokens if usage is not None else None
                ),
                total_tokens=usage.total_tokens if usage is not None else None,
            ),
        )

    async def _create_text_response(self, system_prompt: str, user_input: str) -> str:
        self._ensure_configured()
        try:
            response = await self._client.responses.create(
                model=self._settings.openai_model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input},
                ],
                max_output_tokens=self._settings.openai_max_output_tokens,
                temperature=self._settings.openai_temperature,
                store=False,
            )
        except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
            raise AIProviderError("OpenAI API request failed") from exc

        output_text = response.output_text.strip()
        if not output_text:
            raise AIProviderError("OpenAI API returned an empty response")
        return output_text

    def _ensure_configured(self) -> None:
        if not self._settings.is_openai_configured:
            raise AIConfigurationError("OPENAI_API_KEY is not configured")
