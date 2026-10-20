import json
from pathlib import Path

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import SecretStr
from pytest import MonkeyPatch

from app import product_ai_main
from app.core.config import Settings, get_settings
from app.mana_ai.application.child_safety import ChildSafetyService
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.child_safety import SafetyModelDecision
from app.mana_ai.domain.enums import AnalysisVerdict, ManaAICapability
from app.mana_ai.domain.responses import ModelAnalysis
from app.services.child_safety_model import OpenAIChildSafetyModel
from app.services.child_safety_prompts import ChildSafetyPromptBuilder
from tests.mana_ai_fixtures import details_for, request_for
from tests.test_child_safety_service import Clock
from tests.test_child_safety_store import limits, store, target
from tests.test_parent_chat import Children
from tests.test_parent_chat_adapters import model_payload
from tests.test_parent_chat_api import BACKEND_TOKEN, HEADERS
from tests.test_parent_touch_evidence import TouchModel


@pytest.mark.parametrize(
    "capability",
    [
        capability
        for capability in ManaAICapability
        if capability != ManaAICapability.PARENT_COPILOT
    ],
)
async def test_every_protective_api_runs_through_the_actual_sdk_and_owning_validation(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    capability: ManaAICapability,
) -> None:
    config = Settings(
        _env_file=None,
        openai_api_key=SecretStr("unit-openai"),
        app_api_key=SecretStr(BACKEND_TOKEN),
    )
    monkeypatch.setattr(product_ai_main, "get_settings", lambda: config)
    repository, children, touch_model = await store(tmp_path / "all.db"), Children(), TouchModel()
    request = request_for(capability)
    request = request.model_copy(
        update={
            "subject": request.subject.model_copy(update={"subject_id": "124"}),
        }
    )
    payload = model_payload()
    payload["output"][0]["content"][0]["text"] = SafetyModelDecision(
        analysis=ModelAnalysis(
            verdict=AnalysisVerdict.INSUFFICIENT_DATA,
            summary="Only the bounded dated fixture was reviewed.",
            details=details_for(capability),
        ),
        followup_summary=None,
        question=None,
    ).model_dump_json()
    requests: list[httpx.Request] = []

    def handle(incoming: httpx.Request) -> httpx.Response:
        requests.append(incoming)
        return httpx.Response(
            200,
            json={"input_tokens": 100} if incoming.url.path.endswith("/input_tokens") else payload,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as provider_http:
        adapter = OpenAIChildSafetyModel(
            config,
            client=AsyncOpenAI(
                api_key="unit",
                max_retries=0,
                http_client=provider_http,
            ),
        )
        safety = ChildSafetyService(
            store=repository,
            children=children,
            model=adapter,
            prompts=ChildSafetyPromptBuilder(),
            clock=Clock(),
            limits=limits(),
            max_output_tokens=256,
        )
        touch = ParentTouchService(
            store=repository,
            children=children,
            model=touch_model,
            clock=Clock().now,
            max_output_tokens=512,
            history_turn_limit=2,
            safety=safety,
        )
        app = product_ai_main.create_app()
        app.dependency_overrides[get_settings] = lambda: config
        app.state.parent_chat_service = touch
        path = "/api/v1/mana-ai/child-safety/" + capability.value.replace("_", "-")
        body = target().model_dump(mode="json") | {"analysis": request.model_dump(mode="json")}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://unit"
        ) as api:
            admitted = await api.post(path, json=body, headers=HEADERS)
            assert admitted.status_code == 202, admitted.text
            completed = await safety.process_one()
            assert completed and completed.status == "completed" and completed.result
            assert completed.result.analysis and completed.result.analysis.capability == capability
            assert type(completed.result.analysis.details) is type(details_for(capability))
            assert all(
                not action.executed and action.proposal_only
                for action in completed.result.analysis.proposed_actions
            )
            receipt = await api.post(path, json=body, headers=HEADERS)
            assert receipt.status_code == 202
            assert receipt.json()["job_id"] == admitted.json()["job_id"]
            assert receipt.json()["analysis"]["capability"] == capability
            assert completed.usage and completed.usage.total == 150
            assert (await safety.budget("123")).parent_used_tokens == 150
            assert (await touch.history("123", before=None, limit=30)).quota.used_tokens == 0
    assert children.calls == 1 and touch_model.calls == 0 and len(requests) == 2
    count, generation = (json.loads(item.content) for item in requests)
    assert count == {key: generation[key] for key in count}
    assert generation["store"] is False and "tools" not in generation
