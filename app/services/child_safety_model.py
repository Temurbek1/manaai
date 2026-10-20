"""Reuse the proven strict receipt transport, never its Parent-Touch decision parser."""

from openai.lib._pydantic import to_strict_json_schema
from openai.types.responses.response_text_config_param import ResponseTextConfigParam

from app.mana_ai.application.chat_ports import ChatPrompt
from app.mana_ai.domain.child_safety import SafetyModelDecision
from app.services.parent_chat_model import OpenAIParentChatModel


class OpenAIChildSafetyModel(OpenAIParentChatModel):
    def _text(self, prompt: ChatPrompt) -> ResponseTextConfigParam:
        if prompt.structured_reply or prompt.question is not None:
            raise ValueError("A specialist cannot inherit Parent-Touch's publication protocol")
        return {
            "verbosity": self._verbosity,
            "format": {
                "type": "json_schema",
                "name": "child_safety_decision",
                "strict": True,
                "schema": to_strict_json_schema(SafetyModelDecision),
            },
        }
