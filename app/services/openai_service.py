from typing import TypeVar

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import BaseModel

from app.core.config import Settings
from app.schemas.ai import ChatRequest, ChatResponse, SummarizeRequest, SummarizeResponse

StructuredResponseT = TypeVar("StructuredResponseT", bound=BaseModel)


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
    ) -> StructuredResponseT:
        self._ensure_configured()
        try:
            response = await self._client.responses.parse(
                model=self._settings.openai_model,
                instructions=system_prompt,
                input=user_input,
                max_output_tokens=self._settings.openai_max_output_tokens,
                temperature=self._settings.openai_temperature,
                text_format=text_format,
                store=False,
            )
        except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
            raise AIProviderError("OpenAI API request failed") from exc

        if response.output_parsed is None:
            raise AIProviderError("OpenAI API returned an empty structured response")
        return response.output_parsed

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
