"""The opt-in diagnostic is tested using fake HTTP, never a real API key."""

import json
from pathlib import Path

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import SecretStr
from pytest import MonkeyPatch

from app.mana_operation_ai.infrastructure import chat_model
from scripts import operation_contact_loop_evaluate as diagnostic
from tests.test_inference_failures import wire
from tests.test_native_contact_tool import tool


def test_plan_and_isolated_configuration() -> None:
    plan = diagnostic.plan()
    assert plan["max_calls"] == 2 and plan["cap_microusd"] == 500000
    assert plan["source_attempts"] == plan["real_contacts"] == plan["fake_sends"] == 0
    settings = diagnostic.diagnostic_settings(SecretStr("test-key"))
    assert settings.operation_chat_max_output_tokens == 2048
    assert settings.operation_model_selection_enabled
    assert not settings.operation_allow_self_approval


@pytest.mark.parametrize("lost", [False, True])
async def test_fresh_diagnostic_pairs_sql_result_and_never_replays_unknown(
    monkeypatch: MonkeyPatch, tmp_path: Path, lost: bool
) -> None:
    calls: list[dict[str, object]] = []

    async def transport(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        payload = wire(body["model"], "chat")
        if len(calls) == 1:
            payload["output"] += [
                {
                    "id": "rs_test",
                    "type": "reasoning",
                    "summary": [],
                    "encrypted_content": "opaque-synthetic-only",
                },
                tool(),
            ]
        else:
            assert len(calls) == 2 and body["tool_choice"] == "none"
            assert diagnostic.CONDITION in json.dumps(body, ensure_ascii=False)
            outputs = [item for item in body["input"] if item["type"] == "function_call_output"]
            assert len(outputs) == 1
            observation = json.loads(outputs[0]["output"])
            assert observation["status"] == "proposed" and observation["delivered"] is False
            assert observation["message"]["language"] == "uz"
            assert observation["lifecycle"]["preparation_recorded"] is True
            assert observation["lifecycle"]["next_human_step"] == "separate_human_approval"
            if lost:
                raise httpx.ReadTimeout("PRIVATE lost receipt", request=request)
        return httpx.Response(200, json=payload)

    def client(**kwargs: object) -> AsyncOpenAI:
        assert kwargs["max_retries"] == 0
        return AsyncOpenAI(
            api_key="test-key",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        )

    monkeypatch.setattr(chat_model, "AsyncOpenAI", client)
    monkeypatch.setattr(
        diagnostic, "get_settings", lambda: diagnostic.diagnostic_settings(SecretStr("test-key"))
    )
    directory = tmp_path / "fresh"
    result = await diagnostic.run(directory)
    assert result["status"] == ("failed" if lost else "completed")
    assert result["replay_same_turn"] is True
    assert len(calls) == 2 and result["fake_target_reads"] == 1 and result["fake_sends"] == 0
    accounting = result["accounting"]
    assert isinstance(accounting, dict) and accounting["calls"] == 2
    assert (accounting["unknown_hold_microusd"] > 0) is lost
    assert "PRIVATE" not in json.dumps(result)
    assert result["quality_status"] == "manual_review_pending"
    with pytest.raises(FileExistsError):
        await diagnostic.run(directory)
    assert len(calls) == 2
