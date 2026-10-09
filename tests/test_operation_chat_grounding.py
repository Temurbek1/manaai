"""Offline regression guards from the separately approved synthetic QA batch."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from pytest import MonkeyPatch
from sqlalchemy import select

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatTurnOutput
from app.mana_operation_ai.application.chat_service import (
    INSTRUCTIONS,
    OperationChatService,
    allowed_chat_next_actions,
    chat_card_purposes,
    chat_read_confirmation,
)
from app.mana_operation_ai.domain.chat import (
    AnalysisRequest,
    ChatAgent,
    ChatNextAction,
    ChatReadConfirmation,
    ChatReply,
    ChatTurn,
    ProductScope,
)
from app.mana_operation_ai.domain.models import AgentReport
from app.mana_operation_ai.infrastructure.persistence.models import ChatTurnRow
from tests.test_operation_api import configure_operation_env, headers
from tests.test_operation_chat import BASE, FakeConversation
from tests.test_operation_cost_ledger import Clock


@pytest.mark.parametrize("product", ["mana", "360rec"])
@pytest.mark.parametrize("parent_enabled", [False, True])
@pytest.mark.parametrize(
    "agent", ["operations-orchestrator", "growth-agent", "retention-agent", "technical-agent"]
)
def test_confirmation_cards_are_scoped_without_new_execution_authority(
    agent: ChatAgent, product: ProductScope, parent_enabled: bool
) -> None:
    allowed = allowed_chat_next_actions(
        agent_id=agent, product=product, parent_summary_enabled=parent_enabled
    )
    assert allowed[0] == "none" and len(set(allowed)) == len(allowed)
    assert ("analyze" in allowed) is (agent in {"growth-agent", "retention-agent"})
    assert ("approvals" in allowed) is (agent == "growth-agent")
    assert ("mana_parents" in allowed) is (
        agent == "retention-agent" and product == "mana" and parent_enabled
    )


class WrongCardConversation(FakeConversation):
    def __init__(self, card: ChatNextAction) -> None:
        super().__init__()
        self.card = card

    async def reply(self, *, instructions: str, context: str, owner: str) -> ChatTurnOutput:
        result = await super().reply(instructions=instructions, context=context, owner=owner)
        result.next_action = self.card
        return result


@pytest.mark.parametrize(
    "agent,product,parent_enabled,card,expected",
    [
        ("retention-agent", "360rec", True, "mana_parents", "none"),
        ("retention-agent", "mana", False, "mana_parents", "none"),
        ("retention-agent", "mana", True, "mana_parents", "mana_parents"),
        ("growth-agent", "mana", True, "mana_parents", "none"),
        ("operations-orchestrator", "mana", True, "analyze", "none"),
        ("technical-agent", "360rec", True, "approvals", "none"),
    ],
)
async def test_actual_chat_context_and_reply_enforce_the_same_scoped_cards(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    agent: ChatAgent,
    product: ProductScope,
    parent_enabled: bool,
    card: ChatNextAction,
    expected: ChatNextAction,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "grounding.db")
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        service: OperationChatService = app.state.operation_chat_service
        service.availability.parent_summary_enabled = parent_enabled
        model = WrongCardConversation(card)
        service._model = model
        auth = headers("operator", "viewer")
        topic = (
            await client.post(
                f"{BASE}/topics",
                headers=auth,
                json={"agent_id": agent, "product": product, "title": "Grounding regression"},
            )
        ).json()
        payload = {"request_id": str(uuid4()), "message": "Какие данные подтверждены?"}
        url = f"{BASE}/topics/{topic['topic_id']}/messages"
        answer = await client.post(url, headers=auth, json=payload)
        assert answer.status_code == 200 and answer.json()["status"] == "completed"
        assert answer.json()["next_action"] == expected
        confirmation = answer.json()["read_confirmation"]
        if expected == "mana_parents":
            assert confirmation == {
                "kind": "mana_parents",
                "product": "mana",
                "capability_key": "retention.parents.analyze",
                "confirmation_required": True,
                "admission_checks": ["access", "product_scope", "cooldown", "budget"],
                "minimum_interval_seconds": 21600,
            }
        else:
            assert confirmation is None
        context = model.contexts[0]
        allowed = allowed_chat_next_actions(
            agent_id=agent, product=product, parent_summary_enabled=parent_enabled
        )
        assert context["allowed_next_actions"] == allowed
        default_capability_key = (
            app.state.operation_admin_service.default_capability_key(agent)
            if "analyze" in allowed
            else None
        )
        assert context["card_purposes"] == chat_card_purposes(
            allowed, default_capability_key=default_capability_key
        )
        if "analyze" in allowed:
            assert default_capability_key in context["card_purposes"]["analyze"]
        if agent == "retention-agent":
            assert "NOT a Parent API" in context["card_purposes"]["analyze"]
        assert set(context["card_purposes"]) == set(allowed)
        assert "scope_verified" not in context
        assert context["parent_summary_enabled"] is ("mana_parents" in allowed)
        assert context["saved_reports"] == []
        assert (await client.post(url, headers=auth, json=payload)).json() == answer.json()
        assert len(model.contexts) == 1
        assert (await client.get("/api/v1/admin/operation/runs", headers=auth)).json()["total"] == 0
    get_settings.cache_clear()


@pytest.mark.parametrize("card", ["analyze", "mana_parents", "approvals", "none"])
async def test_read_conditions_survive_restart_without_persisting_a_grant_or_execution(
    monkeypatch: MonkeyPatch, tmp_path: Path, card: ChatNextAction
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "read-conditions.db")
    monkeypatch.setenv("MANAKIDS_PARENT_MIN_INTERVAL_SECONDS", "86400")
    get_settings.cache_clear()
    agent = "retention-agent" if card == "mana_parents" else "growth-agent"
    payload = {"request_id": str(uuid4()), "message": "Предложи следующий шаг, не читай источники."}
    topic_id = ""
    saved: dict[str, object] = {}
    for restarting in (False, True):
        app = create_app()
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
        ):
            service: OperationChatService = app.state.operation_chat_service
            service.availability.parent_summary_enabled = True
            model = WrongCardConversation(card)
            service._model = model
            run = AsyncMock(side_effect=AssertionError("Chat metadata executed an analysis"))
            monkeypatch.setattr(app.state.operation_admin_service, "run_in_background", run)
            auth = headers("operator", "viewer")
            if not restarting:
                topic_id = (
                    await client.post(
                        f"{BASE}/topics",
                        headers=auth,
                        json={"agent_id": agent, "product": "mana", "title": "Read contract"},
                    )
                ).json()["topic_id"]
            url = f"{BASE}/topics/{topic_id}/messages"
            reply = await client.post(url, headers=auth, json=payload)
            assert reply.status_code == 200 and reply.json()["status"] == "completed"
            assert reply.json()["next_action"] == card
            assert reply.json()["analysis_requested"] is False
            assert "лимит" not in reply.json()["answer"]
            confirmation = reply.json()["read_confirmation"]
            if card in {"analyze", "mana_parents"}:
                expected = ChatReadConfirmation(
                    kind="mana_parents" if card == "mana_parents" else "default",
                    product="mana",
                    capability_key="retention.parents.analyze"
                    if card == "mana_parents"
                    else app.state.operation_admin_service.default_capability_key(agent),
                    minimum_interval_seconds=86400 if card == "mana_parents" else None,
                )
                assert confirmation == expected.model_dump(mode="json")
            else:
                assert confirmation is None
            if restarting:
                assert reply.json() == saved
                assert model.contexts == []
            else:
                saved = reply.json()
                assert len(model.contexts) == 1
                assert "read_confirmation" not in model.contexts[0]
            detail = await client.get(f"{BASE}/topics/{topic_id}", headers=auth)
            assert detail.json()["turns"][0] == saved
            async with app.state.operation_database.session_factory() as session:
                row = await session.scalar(select(ChatTurnRow))
                assert row is not None and "read_confirmation" not in row.payload
            if restarting and card == "mana_parents":
                service.availability.parent_summary_enabled = False
                disabled = await client.get(f"{BASE}/topics/{topic_id}", headers=auth)
                assert disabled.json()["turns"][0]["read_confirmation"] is None
                refused = await client.post(
                    f"{BASE}/topics/{topic_id}/analysis",
                    headers=auth,
                    json={"request_id": str(uuid4()), "confirmed": True, "kind": "mana_parents"},
                )
                assert refused.status_code == 403  # Viewer metadata is not operator consent.
                refused_operator = await client.post(
                    f"{BASE}/topics/{topic_id}/analysis",
                    headers=headers("operator", "operator"),
                    json={"request_id": str(uuid4()), "confirmed": True, "kind": "mana_parents"},
                )
                assert refused_operator.status_code == 503
            assert (await client.get("/api/v1/admin/operation/runs", headers=auth)).json()[
                "total"
            ] == 0
            run.assert_not_called()
    get_settings.cache_clear()


def test_read_confirmation_does_not_reinterpret_views_or_missing_capabilities() -> None:
    for action in ("none", "approvals"):
        assert (
            chat_read_confirmation(
                action,
                product="360rec",
                default_capability_key=None,
                parent_minimum_interval_seconds=21600,
            )
            is None
        )
    with pytest.raises(ValueError, match="MANA product"):
        chat_read_confirmation(
            "mana_parents",
            product="360rec",
            default_capability_key=None,
            parent_minimum_interval_seconds=21600,
        )
    with pytest.raises(ValueError, match="actual default capability"):
        chat_read_confirmation(
            "analyze",
            product="mana",
            default_capability_key=None,
            parent_minimum_interval_seconds=21600,
        )


def test_read_conditions_are_additive_and_not_part_of_model_output() -> None:
    turn = ChatTurn(
        turn_id="old-turn",
        topic_id="old-topic",
        request_id=uuid4(),
        message="Old saved message",
        status="completed",
        created_at=datetime(2026, 10, 8, tzinfo=UTC),
    )
    legacy = turn.model_dump(mode="json", exclude={"read_confirmation"})
    assert ChatTurn.model_validate(legacy).read_confirmation is None
    assert "read_confirmation" not in ChatReply.model_json_schema()["properties"]
    assert ChatReply.model_json_schema()["additionalProperties"] is False
    with pytest.raises(ValidationError):
        AnalysisRequest.model_validate(
            {
                "request_id": str(uuid4()),
                "confirmed": True,
                "kind": "mana_parents",
                "read_confirmation": {"confirmation_required": False},
            }
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("confirmation_required", False),
        ("admission_checks", ["access", "product_scope", "cooldown"]),
        ("admission_checks", ["budget", "cooldown", "product_scope", "access"]),
        ("minimum_interval_seconds", 21599),
        ("minimum_interval_seconds", 86401),
    ],
)
def test_read_contract_cannot_omit_conditions_or_loosen_the_interval(
    field: str, value: object
) -> None:
    policy = ChatReadConfirmation(
        kind="mana_parents",
        product="mana",
        capability_key="retention.parents.analyze",
        minimum_interval_seconds=21600,
    ).model_dump(mode="json")
    policy[field] = value
    with pytest.raises(ValidationError):
        ChatReadConfirmation.model_validate(policy)


def test_analysis_purpose_requires_an_actual_default_capability() -> None:
    with pytest.raises(ValueError, match="actual default capability"):
        chat_card_purposes(["none", "analyze"], default_capability_key=None)
    assert set(chat_card_purposes(["none"], default_capability_key=None)) == {"none"}


@pytest.mark.parametrize(
    "summary,notes,shortened",
    [
        ("1000 children; 500 active. Parent counts are unknown.", ["No mobile telemetry"], False),
        ("Synthetic report appendix. " * 200, ["No mobile telemetry"], True),
        ("1000 children; 500 active.", ["Synthetic limitation. " * 20], True),
        ("1000 children; 500 active.", ["Synthetic limitation"] * 11, True),
    ],
)
async def test_actual_model_context_distinguishes_collection_time_and_minimized_excerpts(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    summary: str,
    notes: list[str],
    shortened: bool,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "dates.db")
    now = datetime(2026, 10, 8, 3, tzinfo=UTC)
    collected = now - timedelta(hours=3)
    report = AgentReport(
        report_id="source-time-regression",
        run_id="saved-run",
        agent_id="retention-agent",
        capability_key="retention.engagement.analyze",
        report_type="retention_engagement_analysis",
        period_start=collected - timedelta(days=7),
        period_end=collected,
        created_at=now,
        structured={
            "product": "mana",
            "scope_verified": True,
            "scope_basis": "approved_source_binding",
            "collected_at": collected.isoformat(),
            "fresh_until": (collected + timedelta(hours=6)).isoformat(),
            "refresh_status": "cached",
        },
        human_readable=summary,
        data_quality_notes=notes,
    )
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        service: OperationChatService = app.state.operation_chat_service
        service._clock = Clock(now)
        monkeypatch.setattr(service._admin, "list_reports", AsyncMock(return_value=([report], 1)))
        model = FakeConversation()
        service._model = model
        auth = headers("operator", "viewer")
        topic = (
            await client.post(
                f"{BASE}/topics",
                headers=auth,
                json={"agent_id": "retention-agent", "product": "mana", "title": "Data dates"},
            )
        ).json()
        answer = await client.post(
            f"{BASE}/topics/{topic['topic_id']}/messages",
            headers=auth,
            json={"request_id": str(uuid4()), "message": "На какую дату эти данные?"},
        )
        assert answer.status_code == 200 and answer.json()["status"] == "completed"
        context = json.loads(json.dumps(model.contexts[0]))
        evidence = context["saved_reports"][0]
        assert context["report_text_shortened"] is shortened
        assert len(evidence["summary"]) <= 4000
        assert len(evidence["limitations"]) <= 10
        assert all(len(note) <= 300 for note in evidence["limitations"])
        assert evidence["capability_key"] == "retention.engagement.analyze"
        assert evidence["report_type"] == "retention_engagement_analysis"
        assert evidence["collected_at"] == collected.isoformat()
        assert evidence["report_created_at"] == now.isoformat()
        assert evidence["collected_at"] != evidence["report_created_at"] and "date" not in evidence
        assert datetime.fromisoformat(answer.json()["sources"][0]["collected_at"]) == collected
    get_settings.cache_clear()


async def test_actual_context_preserves_user_constraints_beyond_old_prefix_limit(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "long-user-message.db")
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        service: OperationChatService = app.state.operation_chat_service
        model = FakeConversation()
        service._model = model
        auth = headers("operator", "viewer")
        topic = (
            await client.post(
                f"{BASE}/topics",
                headers=auth,
                json={"agent_id": "retention-agent", "product": "mana", "title": "History limits"},
            )
        ).json()
        url = f"{BASE}/topics/{topic['topic_id']}/messages"
        previous = "Synthetic context. " * 170 + "Бюджет $17/месяц. Не контактировать с родителями."
        assert 3000 < len(previous) < 6000
        first = await client.post(
            url, headers=auth, json={"request_id": str(uuid4()), "message": previous}
        )
        assert first.status_code == 200 and first.json()["status"] == "completed"
        second = await client.post(
            url,
            headers=auth,
            json={"request_id": str(uuid4()), "message": "Продолжим с теми же ограничениями."},
        )
        assert second.status_code == 200 and second.json()["status"] == "completed"
        context = json.loads(json.dumps(model.contexts[-1]))
        assert context["history"][0]["user"] == previous
        assert context["older_turns_omitted"] == 0
        assert len(json.dumps(model.contexts[-1], ensure_ascii=False).encode()) <= 24_000
    get_settings.cache_clear()


class OutputContractConversation(FakeConversation):
    """Assert prompt transport, not semantic compliance by a real model."""

    def __init__(self, output: ChatReply) -> None:
        super().__init__()
        self.output = output

    async def reply(self, *, instructions: str, context: str, owner: str) -> ChatTurnOutput:
        assert instructions == INSTRUCTIONS
        # Transport/size assertions, not proof that a real model follows the rules.
        assert len(instructions.encode()) <= 8192
        for rule in (
            "give the requested calculation in answer now",
            "percentage-point changes and relative percent",
            "NOT prove the same people remained active, no churn or a cause",
            "Different time-window totals",
            "plan defaults to []",
            "A card does NOT need a",
            "fits the requested metric in card_purposes",
            "Even after confirmation, scope, access",
            "Never divide active parents by child inventory",
            "Geographic active-user/event counts and profile cities are NOT orders",
            "For a standalone greeting or thanks, answer in one short natural sentence",
            "a greeting alone needs no capability disclaimer",
        ):
            assert rule in instructions
        result = await super().reply(instructions=instructions, context=context, owner=owner)
        result.answer = self.output.answer
        result.plan = self.output.plan
        result.next_action = self.output.next_action
        return result


@pytest.mark.parametrize(
    "agent,message,output",
    [
        (
            "retention-agent",
            "Что изменилось: 900 детей/180 активных против 1200/180? Посчитай разницу.",
            ChatReply(
                answer=(
                    "Старые данные устарели. По denominator-old/new: активных по-прежнему "
                    "180, детей +300, доля 20% → 15%: −5 п.п., −25% относительно 20%. "
                    "Это не доказывает отсутствие оттока или тот же состав активных."
                ),
                plan=[],
                next_action="none",
            ),
        ),
        (
            "retention-agent",
            "DAU=130 и WAU=910. Это D1 retention?",
            ChatReply(
                answer="Нет. Разные временные окна не дают возврат одной когорты на D1.",
                plan=[],
                next_action="none",
            ),
        ),
        (
            "retention-agent",
            "Покажи подтверждение одной страницы тарифов и связей родителей MANA.",
            ChatReply(
                answer=(
                    "Карточка подтверждения одной страницы. Доступ, кулдаун и бюджет "
                    "могут остановить чтение; оно ещё не выполнено."
                ),
                plan=[],
                next_action="mana_parents",
            ),
        ),
        (
            "growth-agent",
            "Покажи существующие предложения, без согласования и исполнения.",
            ChatReply(
                answer="Можно открыть сохранённые предложения. Это не их согласование.",
                plan=[],
                next_action="approvals",
            ),
        ),
        (
            "retention-agent",
            "Составь план обсуждения качества сводки, только по сохранённым данным.",
            ChatReply(
                answer="Обсудим определения и ограничения сохранённой сводки.",
                plan=["Сопоставить определения метрик", "Обсудить ограничения данных"],
                next_action="none",
            ),
        ),
    ],
)
async def test_actual_route_forwards_output_contract_without_semantic_postprocessing(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    agent: ChatAgent,
    message: str,
    output: ChatReply,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "output-contract.db")
    now = datetime(2026, 10, 8, 12, tzinfo=UTC)
    reports = []
    for suffix, hours, summary in (
        ("new", 1, "1200 children; 180 active; active share 15%."),
        ("old", 7, "900 children; 180 active; active share 20%."),
    ):
        collected = now - timedelta(hours=hours)
        reports.append(
            AgentReport(
                report_id=f"denominator-{suffix}",
                run_id=f"saved-{suffix}",
                agent_id="retention-agent",
                capability_key="retention.engagement.analyze",
                report_type="retention_engagement_analysis",
                period_start=collected - timedelta(days=7),
                period_end=collected,
                created_at=now,
                structured={
                    "product": "mana",
                    "scope_verified": True,
                    "scope_basis": "approved_source_binding",
                    "collected_at": collected.isoformat(),
                    "fresh_until": (collected + timedelta(hours=6)).isoformat(),
                    "refresh_status": "cached",
                },
                human_readable=summary,
                data_quality_notes=["Same metric definition; no cohort membership data."],
            )
        )
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        service: OperationChatService = app.state.operation_chat_service
        service._clock = Clock(now)
        service.availability.parent_summary_enabled = True
        monkeypatch.setattr(service._admin, "list_reports", AsyncMock(return_value=(reports, 2)))
        model = OutputContractConversation(output)
        service._model = model
        auth = headers("operator", "viewer")
        topic = (
            await client.post(
                f"{BASE}/topics",
                headers=auth,
                json={"agent_id": agent, "product": "mana", "title": "Output policy"},
            )
        ).json()
        url = f"{BASE}/topics/{topic['topic_id']}/messages"
        payload = {"request_id": str(uuid4()), "message": message}
        answer = await client.post(url, headers=auth, json=payload)
        assert answer.status_code == 200
        body = answer.json()
        assert body["status"] == "completed"
        assert body["answer"] == output.answer
        assert body["plan"] == output.plan
        assert body["next_action"] == output.next_action
        assert (await client.post(url, headers=auth, json=payload)).json() == body
        assert len(model.contexts) == 1
        context = model.contexts[0]
        assert context["message"] == message
        if agent == "retention-agent":
            evidence = json.loads(json.dumps(context["saved_reports"]))
            assert [item["id"] for item in evidence] == ["denominator-new", "denominator-old"]
            assert [item["refresh_status"] for item in evidence] == ["cached", "stale"]
            assert "Even after confirmation" in str(context["card_purposes"])
        assert (await client.get("/api/v1/admin/operation/runs", headers=auth)).json()["total"] == 0
    get_settings.cache_clear()
