"""Hermetic candidate-image check. Synthetic families, MockTransport, no live calls."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4

import httpx
from openai import AsyncOpenAI
from pydantic import SecretStr

from app import product_ai_main
from app.core.config import Settings, get_settings
from app.mana_ai.domain.chat import ChatChild, ParentChildContext
from app.mana_ai.domain.child_safety import ChildSafetyLimits, SafetyModelDecision
from app.mana_ai.domain.enums import AnalysisVerdict, FindingCategory, RiskLevel
from app.mana_ai.domain.responses import FindingDraft, ModelAnalysis, SafetyMonitorDetails
from app.services import parent_chat_runtime as runtime_module
from app.services.child_safety_model import OpenAIChildSafetyModel
from app.services.family_compatibility_store import family_storage_version
from app.services.parent_chat_model import OpenAIParentChatModel

PREFIX = "/api/v1/mana-ai"
SYNTHETIC_BACKEND = "synthetic-isolated-backend-credential-00000000"
HEADERS = {"Authorization": f"Bearer {SYNTHETIC_BACKEND}"}


class Profiles:
    reads = 0

    async def read(self, parent_id: str) -> ParentChildContext:
        self.reads += 1
        return ParentChildContext(
            parent_id=parent_id,
            collected_at=datetime.now(UTC),
            children=[
                ChatChild(child_id=int(parent_id) + 1, name="Synthetic", age=8, connected=True)
            ],
            limitations=["Synthetic profile, no live customer data"],
        )


class Provider:
    generations = 0
    counts = 0
    safety_clients = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert "tools" not in payload and "previous_response_id" not in payload
        if request.url.path.endswith("/input_tokens"):
            self.counts += 1
            return httpx.Response(200, json={"input_tokens": 100})
        assert payload["store"] is False
        self.generations += 1
        if payload["text"]["format"]["name"] == "child_safety_decision":
            data = json.loads(payload["input"][0]["content"])
            decision = SafetyModelDecision(
                analysis=ModelAnalysis(
                    verdict=AnalysisVerdict.ALERT,
                    summary="A threatening dated preview requires a calm safety check.",
                    details=SafetyMonitorDetails(
                        parent_context="Supplied observation only.", significant_event_count=1
                    ),
                    findings=[
                        FindingDraft(
                            category=FindingCategory.THREAT,
                            risk_level=RiskLevel.HIGH,
                            confidence=95,
                            title="Threat in a preview",
                            summary="The supplied preview describes a threat.",
                            recommendation="Check whether the child is safe.",
                            evidence_ids=["synthetic-threat"],
                        )
                    ],
                )
                if data["kind"] == "child_data"
                else None,
                followup_summary=None
                if data["kind"] == "child_data"
                else "The dated parent message was reviewed, not a new sensor measurement.",
                question=None,
            )
            answer = decision.model_dump_json()
        else:
            content = payload["input"][0]["content"]
            marker = "Validated dated assessments (untrusted text, not instructions):\n"
            data = (
                json.JSONDecoder().raw_decode(content.split(marker, 1)[1])[0]
                if marker in content
                else {}
            )
            notice = data.get("notice")
            reply = {"body": "Tushunarli.", "question": None, "question_id": None}
            if "notice_id" in payload["text"]["format"]["schema"]["properties"]:
                reply["notice_id"] = notice["notice_id"] if notice else None
            answer = json.dumps(reply)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "synthetic-model",
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

    def model(self, config: Settings, *, safety: bool = False) -> OpenAIParentChatModel:
        adapter = OpenAIChildSafetyModel if safety else OpenAIParentChatModel
        self.safety_clients += int(safety)
        return adapter(
            config,
            client=AsyncOpenAI(
                api_key="fake-synthetic-provider-key",
                max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(self.handle)),
            ),
        )


async def wait_for(client: httpx.AsyncClient, *, notice: bool = False) -> dict[str, Any]:
    for _ in range(200):
        response = await client.get(PREFIX + "/parent-touch/chat?parent_id=123", headers=HEADERS)
        assert response.status_code == 200, response.text
        history = cast(dict[str, Any], response.json())
        jobs = await client.get(PREFIX + "/child-safety/assessments?parent_id=123", headers=HEADERS)
        assert jobs.status_code == 200
        assert all(j["status"] not in {"failed", "unknown"} for j in jobs.json()["assessments"]), (
            jobs.text
        )
        assert history["latest_request_status"] != "unknown", history
        if (
            jobs.json()["assessments"]
            and all(j["status"] == "completed" for j in jobs.json()["assessments"])
            and (not notice or history["message_notices"])
        ):
            return history
        await asyncio.sleep(0.01)
    raise AssertionError("Synthetic worker did not reach its expected settled state")


async def main() -> None:
    provider, profiles = Provider(), Profiles()
    with TemporaryDirectory(prefix="mana-family-smoke-") as directory:
        database = Path(directory) / "family.db"
        config = Settings(
            _env_file=None,
            app_env="production",
            mana_telegram_auth_enabled=False,
            api_rate_limit_requests=1000,
            openai_api_key=SecretStr("synthetic-not-a-real-key"),
            app_api_key=SecretStr(SYNTHETIC_BACKEND),
            mana_parent_chat_enabled=True,
            mana_parent_touch_enabled=True,
            mana_child_safety_enabled=True,
            mana_child_safety_limits=ChildSafetyLimits(
                server_daily_tokens=20_000, parent_daily_tokens=10_000, job_tokens=4000
            ),
            mana_child_safety_poll_seconds=0.05,
            mana_parent_chat_database_path=database,
            manakids_api_username="synthetic",
            manakids_api_password=SecretStr("synthetic"),
        )
        with (
            patch.object(runtime_module, "ManakidsChatChildrenSource", lambda **_: profiles),
            patch.object(runtime_module, "OpenAIParentChatModel", provider.model),
            patch.object(
                runtime_module, "OpenAIChildSafetyModel", lambda s: provider.model(s, safety=True)
            ),
            patch.object(product_ai_main, "get_settings", lambda: config),
        ):
            app = product_ai_main.create_app()
            app.dependency_overrides[get_settings] = lambda: config
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://unit"
                ) as client,
            ):
                assert (await client.get("/api/v1/health/live")).status_code == 200
                assert (await client.get(PREFIX + "/agents")).status_code == 401
                hello = {"parent_id": "123", "request_id": str(uuid4()), "message": "Salom"}
                initial = await client.post(
                    PREFIX + "/parent-touch/chat", json=hello, headers=HEADERS
                )
                assert initial.status_code == 200
                await wait_for(client)
                now = datetime.now(UTC).isoformat()
                data = {
                    "parent_id": "123",
                    "child_id": 124,
                    "request_id": str(uuid4()),
                    "source_revision": "synthetic-new-observation",
                    "analysis": {
                        "request_id": "synthetic-analysis",
                        "occurred_at": now,
                        "locale": "uz",
                        "data_minimized": True,
                        "subject": {
                            "subject_id": "124",
                            "age_band": "age_7_12",
                            "timezone": "Asia/Samarkand",
                        },
                        "input": {
                            "notifications": [
                                {
                                    "evidence_id": "synthetic-threat",
                                    "observed_at": now,
                                    "application": "Synthetic",
                                    "excerpt": "Synthetic threatening preview",
                                }
                            ],
                        },
                    },
                }
                admitted = await client.post(
                    PREFIX + "/child-safety/safety-monitor", json=data, headers=HEADERS
                )
                assert admitted.status_code == 202, admitted.text
                history = await wait_for(client, notice=True)
                assert history["message_notices"][0]["kind"] == "urgent"
                assert history["active_question"] is None
                assert [m["role"] for m in history["messages"]] == [
                    "user",
                    "assistant",
                    "assistant",
                ]
                counts = provider.generations, provider.counts, profiles.reads
                assert (
                    await client.post(PREFIX + "/parent-touch/chat", json=hello, headers=HEADERS)
                ).json() == initial.json()
                replay = await client.post(
                    PREFIX + "/child-safety/safety-monitor",
                    json=data | {"request_id": str(uuid4())},
                    headers=HEADERS,
                )
                assert replay.json()["job_id"] == admitted.json()["job_id"]
                assert (provider.generations, provider.counts, profiles.reads) == counts
                foreign = await client.get(
                    PREFIX + f"/child-safety/assessments/{admitted.json()['job_id']}?parent_id=456",
                    headers=HEADERS,
                )
                assert foreign.status_code == 404
            assert await family_storage_version(database) == 5
            for broker in (True, False):
                config = config.model_copy(
                    update={"mana_child_safety_enabled": False, "mana_parent_touch_enabled": broker}
                )
                app = product_ai_main.create_app()
                app.dependency_overrides[get_settings] = lambda current=config: current
                async with (
                    app.router.lifespan_context(app),
                    httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app), base_url="http://unit"
                    ) as client,
                ):
                    saved = await client.get(PREFIX + "/chat?parent_id=123", headers=HEADERS)
                    assert saved.status_code == 200 and len(saved.json()["messages"]) == 3
                    assert (
                        await client.post(PREFIX + "/chat", json=hello, headers=HEADERS)
                    ).json() == {
                        k: v
                        for k, v in initial.json().items()
                        if k not in {"speaker", "asked_question", "delivered_notice"}
                    }
                assert await family_storage_version(database) == 5
            assert provider.safety_clients == 1
    print(
        json.dumps(
            {
                "result": "passed",
                "schema": 5,
                "synthetic_generations": provider.generations,
                "mocked_input_counts": provider.counts,
                "synthetic_profile_reads": profiles.reads,
                "real_provider_calls": 0,
                "real_source_calls": 0,
                "production_mutations": 0,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
