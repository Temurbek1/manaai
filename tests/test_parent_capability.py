from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatTurnOutput
from app.mana_operation_ai.application.ports import ProviderPermanentError
from app.mana_operation_ai.application.retention.constants import PARENTS_CAPABILITY_KEY
from app.mana_operation_ai.application.runtime import SystemClock
from app.mana_operation_ai.domain.enums import TriggerType, UserRole
from app.mana_operation_ai.domain.parents import ParentSummary
from app.mana_operation_ai.infrastructure.retention.parents import (
    FakeParentSummaryAdapter,
    UnavailableParentSummaryAdapter,
)
from tests.test_operation_api import configure_operation_env, headers
from tests.test_operation_chat import BASE, FakeConversation


class ParentConversation(FakeConversation):
    async def reply(self, *, instructions: str, context: str, owner: str) -> ChatTurnOutput:
        result = await super().reply(instructions=instructions, context=context, owner=owner)
        result.next_action = "mana_parents"
        return result


async def test_parent_run_chat_rbac_idempotency_cooldown_and_product_isolation(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "parents.db")
    calls = 0

    async def fake_collect(self: UnavailableParentSummaryAdapter) -> ParentSummary:
        nonlocal calls
        calls += 1
        return await FakeParentSummaryAdapter(SystemClock()).collect_summary()

    monkeypatch.setattr(UnavailableParentSummaryAdapter, "collect_summary", fake_collect)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        service = app.state.operation_chat_service
        service.availability.parent_summary_enabled = True
        model = ParentConversation()
        service._model = model
        operator = headers("parent-admin", "operator")
        topics = {}
        for product in ["mana", "360rec"]:
            topics[product] = (
                await client.post(
                    f"{BASE}/topics",
                    headers=operator,
                    json={
                        "agent_id": "retention-agent",
                        "product": product,
                        "title": "Родители",
                    },
                )
            ).json()["topic_id"]
        payload = {"request_id": str(uuid4()), "confirmed": True, "kind": "mana_parents"}
        assert (
            await client.post(
                f"{BASE}/topics/{topics['mana']}/analysis",
                headers=headers("parent-admin", "viewer"),
                json=payload,
            )
        ).status_code == 403
        assert (
            await client.post(
                f"{BASE}/topics/{topics['360rec']}/analysis", headers=operator, json=payload
            )
        ).status_code == 403
        assert calls == 0
        accepted = await client.post(
            f"{BASE}/topics/{topics['mana']}/analysis", headers=operator, json=payload
        )
        assert accepted.status_code == 202
        assert accepted.json()["analysis_kind"] == "mana_parents"
        assert calls == 1
        replay = await client.post(
            f"{BASE}/topics/{topics['mana']}/analysis", headers=operator, json=payload
        )
        assert replay.json() == accepted.json() and calls == 1
        state = await client.get(
            f"{BASE}/topics/{topics['mana']}/analysis/{accepted.json()['turn_id']}",
            headers=operator,
        )
        assert state.json()["state"] == "completed"
        assert "MANA" in state.json()["summary"]
        for product in ["mana", "360rec"]:
            answer = await client.post(
                f"{BASE}/topics/{topics[product]}/messages",
                headers=operator,
                json={
                    "request_id": str(uuid4()),
                    "message": "Какие данные доступны?",
                },
            )
            assert answer.status_code == 200
            reports = cast(list[dict[str, object]], model.contexts[-1]["saved_reports"])
            if product == "mana":
                assert reports and reports[0]["scope_verified"] and reports[0]["product"] == "mana"
                assert answer.json()["sources"][0]["scope_verified"] is True
                assert answer.json()["next_action"] == "mana_parents"
            else:
                assert reports == [] and answer.json()["sources"] == []
                assert answer.json()["next_action"] == "none"
        assert calls == 1
        repository = app.state.operation_repository
        schedules = await repository.list_schedules("retention-agent", PARENTS_CAPABILITY_KEY)
        assert schedules == []
        runner = app.state.operation_agent_service
        with pytest.raises(ProviderPermanentError, match="cooldown"):
            await runner.run_now(
                agent_id="retention-agent",
                capability_key=PARENTS_CAPABILITY_KEY,
                job_type="analysis",
                trigger=TriggerType.USER,
                actor_id="another-admin",
                actor_role=UserRole.OPERATOR,
                idempotency_key="new-id",
            )
        with pytest.raises(ProviderPermanentError, match="manual"):
            await runner.run_now(
                agent_id="retention-agent",
                capability_key=PARENTS_CAPABILITY_KEY,
                job_type="analysis",
                trigger=TriggerType.SCHEDULE,
                actor_id="scheduler",
                actor_role=UserRole.OPERATOR,
                idempotency_key="no-scheduler",
            )
        assert calls == 1
    get_settings.cache_clear()


async def test_parent_disabled_does_not_call_provider(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "disabled.db")
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        operator = headers("operator", "operator")
        topic = (
            await client.post(
                f"{BASE}/topics",
                headers=operator,
                json={
                    "agent_id": "retention-agent",
                    "product": "mana",
                    "title": "Родители",
                },
            )
        ).json()
        response = await client.post(
            f"{BASE}/topics/{topic['topic_id']}/analysis",
            headers=operator,
            json={
                "request_id": str(uuid4()),
                "confirmed": True,
                "kind": "mana_parents",
            },
        )
        assert response.status_code == 503
        _, count = await app.state.operation_repository.list_runs()
        assert count == 0
    get_settings.cache_clear()


async def test_parent_failure_cooldown_survives_restart(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "restart.db")
    calls = 0

    async def denied(self: UnavailableParentSummaryAdapter) -> ParentSummary:
        nonlocal calls
        calls += 1
        raise ProviderPermanentError("Parent read HTTP 403")

    monkeypatch.setattr(UnavailableParentSummaryAdapter, "collect_summary", denied)
    for expected in ["403", "cooldown"]:
        app = create_app()
        async with app.router.lifespan_context(app):
            with pytest.raises(ProviderPermanentError, match=expected):
                await app.state.operation_agent_service.run_now(
                    agent_id="retention-agent",
                    capability_key=PARENTS_CAPABILITY_KEY,
                    job_type="analysis",
                    trigger=TriggerType.USER,
                    actor_id="operator",
                    actor_role=UserRole.OPERATOR,
                    idempotency_key=str(uuid4()),
                )
    assert calls == 1
    get_settings.cache_clear()
