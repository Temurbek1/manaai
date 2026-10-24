"""New observation contract runs on the actual SDK/SQL/review path with fakes."""

import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from app.services.source_tool_safety_store import (
    SqliteClosedObservationToolSafetyStore,
    SqliteClosedSourceToolSafetyStore,
)
from tests.test_child_app_usage import Usage
from tests.test_child_source_model import Provider, message
from tests.test_family_sources import Clock
from tests.test_source_tool_workflow import NativeProvider, request, setup


class ObservationProvider(NativeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.invalid_kind = False
        self.second_lost = False

    def handle(self, req: httpx.Request) -> httpx.Response:
        data = json.loads(req.content)
        if not req.url.path.endswith("input_tokens"):
            if data["tool_choice"] == "auto":
                assert data["tools"][0]["name"] == "read_child_observation"
                self.body["output"] = [
                    {
                        "type": "function_call",
                        "id": "fc_usage",
                        "call_id": "call_usage",
                        "name": "read_child_observation",
                        "status": "completed",
                        "arguments": json.dumps(
                            {
                                "child_alias": "child-1",
                                "kind": "location" if self.invalid_kind else "app_usage",
                            }
                        ),
                    }
                ]
            else:
                if self.second_lost:
                    self.lost = True
                self.body["output"] = [
                    message(
                        json.dumps(
                            {
                                "analysis": None,
                                "followup_summary": (
                                    "Есть частичные счётчики приложений; "
                                    "период и часовой пояс неизвестны."
                                ),
                                "question": None,
                            },
                            ensure_ascii=False,
                        )
                    )
                ]
        return Provider.handle(self, req)


async def test_model_selects_usage_page_and_only_parent_touch_communicates(tmp_path: Path) -> None:
    usage, provider = Usage(Clock()), ObservationProvider()
    runtime = await setup(tmp_path, observation=True, provider=provider, app_usage=usage)
    req = request().model_copy(update={"message": "В каких приложениях ребёнок проводит время?"})
    await runtime.touch.admit_message(req)
    result = await runtime.safety.process_one()
    assert result and result.status == "completed" and result.usage and result.usage.total == 300
    assert usage.calls == 1 and runtime.battery.calls == 0
    assert await runtime.touch.process_reviewed_message()
    done = await runtime.touch.message_state("123", req.request_id)
    assert done.phase == "completed" and done.response
    prompt = runtime.touch_model.prompts[-1]
    facts = json.loads(prompt.messages[0][1])["specialist_guidance"]["source_observations"][0]
    assert facts["returned_apps"] == 2 and facts["total_apps"] == 3 and not facts["complete"]
    assert facts["observed_at"] is None and facts["quality"] == "unverified_period"
    assert prompt.required_observation_dates == () and "child_id" not in facts
    assert (await runtime.safety.budget("123")).server_used_tokens == 300
    assert await runtime.touch.admit_message(req) == done and usage.calls == 1
    with sqlite3.connect(tmp_path / "family.sqlite3") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 12
        stored = json.loads(db.execute("SELECT prepared FROM source_tool_jobs").fetchone()[0])
        assert stored["scope"]["protocol"] == 2
    closed = SqliteClosedObservationToolSafetyStore(
        tmp_path / "family.sqlite3", history_only=True, daily_limit=2000, timezone="Asia/Tashkent"
    )
    await closed.initialize()
    assert await closed.history(
        "123", before=None, limit=20, now=runtime.clock.now()
    ) == await runtime.store.history("123", before=None, limit=20, now=runtime.clock.now())
    with pytest.raises(RuntimeError):
        await SqliteClosedSourceToolSafetyStore(
            tmp_path / "family.sqlite3",
            history_only=True,
            daily_limit=2000,
            timezone="Asia/Tashkent",
        ).initialize()
    await runtime.adapter.close()


@pytest.mark.parametrize("lost", [False, True])
async def test_invalid_kind_is_metered_and_unknown_continuation_keeps_hold(
    tmp_path: Path, lost: bool
) -> None:
    usage, provider = Usage(Clock()), ObservationProvider()
    provider.invalid_kind = not lost
    provider.second_lost = lost
    runtime = await setup(tmp_path, observation=True, provider=provider, app_usage=usage)
    await runtime.touch.admit_message(request())
    result = await runtime.safety.process_one()
    assert result and result.status == ("unknown" if lost else "failed")
    budget = await runtime.safety.budget("123")
    assert budget.server_used_tokens == 150
    assert budget.server_reserved_tokens == (1850 if lost else 0)
    assert usage.calls == int(lost) and runtime.battery.calls == 0
    assert await runtime.safety.process_one() is None
    await runtime.adapter.close()


async def test_queued_v11_turn_keeps_battery_only_protocol_after_v12_upgrade(
    tmp_path: Path,
) -> None:
    old = await setup(tmp_path)
    await old.touch.admit_message(request())
    updated = await setup(tmp_path, observation=True, app_usage=Usage(Clock()))
    result = await updated.safety.process_one()
    assert result and result.status == "completed"
    calls = [c for c in updated.provider.requests if "max_output_tokens" in c]
    assert calls[0]["tools"][0]["name"] == "read_child_battery"
    assert updated.battery.calls == 1
    with sqlite3.connect(tmp_path / "family.sqlite3") as db:
        scope = json.loads(db.execute("SELECT prepared FROM source_tool_jobs").fetchone()[0])[
            "scope"
        ]
        assert "protocol" not in scope
    await old.adapter.close()
    await updated.adapter.close()
