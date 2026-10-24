"""Actual SDK native protocol with an in-memory fictional provider; never network I/O."""

import json

import httpx
from openai import AsyncOpenAI

from app.core.config import Settings
from app.mana_ai.application.chat_ports import ChatPrompt, ParentChatModel
from app.mana_ai.domain.child_safety import SafetyModelDecision
from app.services.child_source_model import OpenAIChildSourceModel


class LabNativeSourceModel(OpenAIChildSourceModel):
    def __init__(self, fallback: ParentChatModel) -> None:
        self._fallback = fallback
        model_name = "lab-simulated-source-not-billed"
        settings = Settings(_env_file=None, openai_api_key="fake-lab-key", openai_model=model_name)
        super().__init__(
            settings,
            client=AsyncOpenAI(
                api_key="fake-lab-key",
                base_url="https://lab-model.invalid/v1",
                max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(self._reply)),
            ),
        )

    async def _reply(self, request: httpx.Request) -> httpx.Response:
        if request.url.host != "lab-model.invalid":
            raise ValueError("The fictional provider cannot access another host")
        payload = json.loads(request.content)
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        data = json.loads(payload["input"][0]["content"])
        results = [item for item in payload["input"] if item.get("type") == "function_call_output"]
        text = " ".join(item["content"] for item in data.get("chat", [])).casefold()
        children = data.get("children", [])
        wants_battery = any(
            word in text for word in ("заряд", "батар", "quvvat", "zaryad", "battery")
        )
        if results:
            facts = json.loads(results[-1]["output"])["facts"]
            summary = (
                f"В сохранённой записи заряд {facts['percent']}%; "
                f"измерение: {facts['observed_at'] or 'время неизвестно'}. Подключение неизвестно."
                if facts["status"] == "available"
                else "Запись заряда отсутствует или неоднозначна; значение неизвестно."
            )
            answer = SafetyModelDecision(
                analysis=None, followup_summary=summary, question=None
            ).model_dump_json()
        elif payload.get("tools") and children and wants_battery:
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "model": self.model_name,
                    "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
                    "output": [
                        {
                            "type": "function_call",
                            "id": "fc_lab_battery",
                            "call_id": "call_lab_battery",
                            "name": "read_child_battery",
                            "status": "completed",
                            "arguments": json.dumps({"child_alias": children[0]["alias"]}),
                        }
                    ],
                },
            )
        else:
            prompt = ChatPrompt(
                payload["instructions"],
                (("user", payload["input"][0]["content"]),),
                safety_parent_review=data["kind"] == "parent_message",
            )
            result = await self._fallback.respond(
                prompt, max_output_tokens=payload["max_output_tokens"]
            )
            assert result.answer is not None
            answer = result.answer
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": self.model_name,
                "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": answer}],
                    }
                ],
            },
        )
