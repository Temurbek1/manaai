import hashlib

from openai import AsyncOpenAI

from app.core.config import Settings
from app.mana_operation_ai.application.chat_ports import ChatTurnOutput
from app.mana_operation_ai.domain.chat import ChatReply


class OpenAIConversationModel:
    """One bounded Responses call per turn, isolated from the audio provider client."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            max_retries=0,
            timeout=45,
        )

    async def reply(self, *, instructions: str, context: str, owner: str) -> ChatTurnOutput:
        response = await self._client.responses.parse(
            model=self._settings.openai_model,
            instructions=instructions,
            input=context,
            max_output_tokens=min(self._settings.openai_max_output_tokens, 2048),
            reasoning={"effort": self._settings.openai_reasoning_effort},
            text={"verbosity": self._settings.openai_verbosity},
            store=False,
            safety_identifier=hashlib.sha256(owner.encode()).hexdigest(),
            text_format=ChatReply,
        )
        if response.status != "completed" or response.output_parsed is None:
            raise RuntimeError("Conversation response did not complete")
        return ChatTurnOutput(
            answer=response.output_parsed.answer,
            model=response.model,
            input_tokens=response.usage.input_tokens if response.usage else None,
            output_tokens=response.usage.output_tokens if response.usage else None,
            plan=response.output_parsed.plan,
            next_action=response.output_parsed.next_action,
        )

    async def close(self) -> None:
        await self._client.close()
