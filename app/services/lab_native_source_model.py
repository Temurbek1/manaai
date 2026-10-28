"""Actual SDK native protocol with an in-memory fictional provider; never network I/O."""

import json
import re
from datetime import date, timedelta

import httpx
from openai import AsyncOpenAI

from app.core.config import Settings
from app.mana_ai.application.chat_ports import ChatPrompt, ParentChatModel
from app.mana_ai.application.compact_source_tools import BODY_KEYS
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
        text = next(
            (
                item["content"]
                for item in reversed(data.get("chat", []))
                if item.get("role") == "user"
            ),
            "",
        ).casefold()
        children = data.get("children", [])
        wants_battery = any(
            word in text for word in ("заряд", "батар", "quvvat", "zaryad", "battery")
        )
        wants_usage = any(word in text for word in ("приложен", "ilova", "app usage"))
        wants_location = any(word in text for word in ("где", "местополож", "qayer", "location"))
        wants_saved = any(word in text for word in ("сохран", "saqlangan", "saved"))
        if results:
            tool_result = json.loads(results[-1]["output"])
            facts = tool_result["facts"]
            summary = (
                "Сохранённая запись недоступна; данные неизвестны. Источник не обновлялся."
                if facts is None
                and (
                    tool_result.get("saved_observation") is not None
                    or tool_result.get("inspection_scope") == "saved_sql_only"
                )
                else f"Запрос за {tool_result['query_calendar_day']}: "
                "ребёнка нет в странице; использование неизвестно."
                if facts is None
                else "Частичная страница счётчиков приложений; период/часовой пояс неизвестны, "
                "это не дневное экранное время."
                if "entries" in facts
                else f"Последняя запись местоположения от {facts['observed_at'] or 'unknown'}. "
                "Текущее местоположение неизвестно; можно проверить карту в приложении."
                if "is_moving" in facts
                else f"В сохранённой записи заряд {facts['percent']}%; "
                f"измерение: {facts['observed_at'] or 'время неизвестно'}. Подключение неизвестно."
                if facts["status"] == "available"
                else "Запись заряда отсутствует или неоднозначна; значение неизвестно."
            )
            answer = SafetyModelDecision(
                analysis=None, followup_summary=summary, question=None
            ).model_dump_json()
        elif (
            payload.get("tools")
            and children
            and (
                wants_battery
                or wants_location
                and "location"
                in payload["tools"][0]["parameters"]["properties"].get("kind", {}).get("enum", [])
                or wants_usage
                and payload["tools"][0]["name"] == "read_child_observation"
            )
        ):
            tool = next(
                (
                    t
                    for t in payload["tools"]
                    if wants_saved and t["name"] == "inspect_saved_child_observation"
                ),
                payload["tools"][0],
            )
            tool_name = tool["name"]
            arguments: dict[str, str | None] = {"child_alias": children[0]["alias"]}
            if tool_name in {"read_child_observation", "inspect_saved_child_observation"}:
                arguments["kind"] = "app_usage" if wants_usage else "battery"
                if wants_location:
                    arguments["kind"] = "location"
                if "calendar_day" in tool["parameters"]["properties"]:
                    arguments["calendar_day"] = None
                    if wants_usage:
                        explicit = re.search(r"\d{4}-\d{2}-\d{2}", text)
                        today = re.search(
                            r"query-calendar today (\d{4}-\d{2}-\d{2})", payload["instructions"]
                        )
                        assert today
                        arguments["kind"] = "app_usage_day"
                        arguments["calendar_day"] = (
                            explicit.group(0)
                            if explicit
                            else (
                                date.fromisoformat(today.group(1)) - timedelta(days=1)
                            ).isoformat()
                        )
            if "access" in tool["parameters"]["properties"]:
                arguments["access"] = "saved_only" if wants_saved else "live"
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
                            "name": tool_name,
                            "status": "completed",
                            "arguments": json.dumps(arguments),
                        }
                    ],
                },
            )
        else:
            # The deterministic fallback consumes the older host key names.
            # Native v5 only renames these keys; restore them losslessly for
            # this fake's semantic matching without changing the SDK request.
            inverse = {value: key for key, value in BODY_KEYS.items()}
            fallback_data = {inverse.get(key, key): value for key, value in data.items()}
            prompt = ChatPrompt(
                payload["instructions"],
                (("user", json.dumps(fallback_data, ensure_ascii=False, separators=(",", ":"))),),
                safety_parent_review=data["kind"] == "parent_message",
                safety_source_review=data["kind"] == "source_review",
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
