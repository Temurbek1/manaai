from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from app.core.config import Settings
from app.schemas.ai import ChatRequest, ChatResponse, SummarizeRequest, SummarizeResponse


class AIProviderError(RuntimeError):
    """Raised when the upstream AI provider cannot serve a request."""


class OpenAIService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.openai_timeout_seconds,
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

    async def _create_text_response(self, system_prompt: str, user_input: str) -> str:
        try:
            response = await self._client.responses.create(
                model=self._settings.openai_model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input},
                ],
                max_output_tokens=self._settings.openai_max_output_tokens,
                temperature=self._settings.openai_temperature,
            )
        except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
            raise AIProviderError("OpenAI API request failed") from exc

        output_text = response.output_text.strip()
        if not output_text:
            raise AIProviderError("OpenAI API returned an empty response")
        return output_text
