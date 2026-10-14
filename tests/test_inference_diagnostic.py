"""The paid diagnostic defaults to offline and has one exclusive local attempt."""

import json
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import httpx
import pytest
from openai import AsyncOpenAI
from pytest import CaptureFixture, MonkeyPatch

from app.core.config import Settings
from app.mana_operation_ai.application.chat_ports import ChatTurnOutput
from app.mana_operation_ai.infrastructure.chat_model import OpenAIConversationModel
from scripts import operation_inference_diagnostic as diagnostic
from tests.test_inference_failures import wire


def test_default_plan_cannot_load_settings_or_construct_a_client(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    def forbidden() -> None:
        raise AssertionError("Plan-only inspection cannot load credentials")

    monkeypatch.setattr(diagnostic, "get_settings", forbidden)
    monkeypatch.setattr(sys, "argv", ["operation_inference_diagnostic.py"])
    diagnostic.main()
    result = json.loads(capsys.readouterr().out)
    assert result["max_calls"] == 1 and result["cap_microusd"] == 50000
    assert result["source_attempts"] == result["production_changes"] == 0
    assert not result["replay_or_retry"]


async def test_an_existing_attempt_is_not_recreated_or_reauthenticated(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    def forbidden() -> None:
        raise AssertionError("An existing party cannot load settings")

    monkeypatch.setattr(diagnostic, "get_settings", forbidden)
    with pytest.raises(FileExistsError):
        await diagnostic.run(tmp_path)


@pytest.mark.parametrize("quota", [False, True])
async def test_single_sdk_boundary_is_bounded_and_records_only_safe_costs(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    quota: bool,
) -> None:
    settings = Settings(_env_file=None, openai_api_key="test-synthetic-key")
    monkeypatch.setattr(diagnostic, "get_settings", lambda: settings)
    calls: list[str] = []
    body = wire(diagnostic.MODEL, "chat")
    body["output"][0]["content"][0]["text"] = '{"answer":"OK","plan":[],"next_action":"none"}'

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if quota:
            return httpx.Response(
                429,
                json={"error": {"code": "insufficient_quota", "message": "PRIVATE SYNTHETIC KEY"}},
            )
        events = [
            {
                "type": "response.output_text.delta",
                "sequence_number": 1,
                "content_index": 0,
                "output_index": 0,
                "item_id": "msg_synthetic",
                "delta": body["output"][0]["content"][0]["text"],
            },
            {"type": "response.completed", "sequence_number": 2, "response": body},
        ]
        text = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=text)

    async def forbidden(*args: object, **kwargs: object) -> httpx.Response:
        raise AssertionError("An isolated diagnostic tried the real network")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)

    class FakeBoundary(OpenAIConversationModel):
        async def stream_reply(
            self, *, instructions: str, context: str, owner: str
        ) -> AsyncGenerator[str | ChatTurnOutput, None]:
            await self._client.close()
            self._client = AsyncOpenAI(
                api_key="test-synthetic-only",
                max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
            )
            async for event in super().stream_reply(
                instructions=instructions, context=context, owner=owner
            ):
                yield event

    monkeypatch.setattr(diagnostic, "OpenAIConversationModel", FakeBoundary)
    directory = tmp_path / "party"
    result = await diagnostic.run(directory)
    assert calls == ["/v1/responses"]
    assert result["status"] == ("failed" if quota else "completed")
    assert "PRIVATE" not in json.dumps(result)
    accounting = result["accounting"]
    assert isinstance(accounting, dict) and accounting["calls"] == 1
    if quota:
        assert result["failure_kind"] == "quota" and result["http_status"] == 429
        assert accounting["unknown_hold_microusd"] > 0 and accounting["known_microusd"] == 0
    else:
        assert accounting["unknown_hold_microusd"] == 0 and accounting["known_microusd"] > 0
    assert json.loads((directory / "result.json").read_text()) == result
    assert settings.operation_chat_model is None  # Do not mutate caller/global configuration.
