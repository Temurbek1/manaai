from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.agent_service import AgentService
from app.mana_operation_ai.application.chat_service import OperationChatService, _report_source
from app.mana_operation_ai.domain.chat import MessageCreate, TopicCreate
from app.mana_operation_ai.domain.models import AgentReport
from app.mana_operation_ai.infrastructure.chat_model import OpenAIConversationModel
from tests.test_operation_cost_ledger import Clock
from tests.test_operation_data_runtime import configure, run


@pytest.mark.asyncio
async def test_budget_fallback_is_dated_scoped_idempotent_and_performs_no_provider_io(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    clock = Clock(datetime(2026, 10, 8, tzinfo=UTC))
    configure(monkeypatch, tmp_path / "fallback.db", clock)
    app = create_app()
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("login/"):
            return httpx.Response(200, json={"access": "fake-access"})
        return httpx.Response(200, json={"count": 0, "results": []})

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client,
    ):
        backend = app.state.operation_backend_activity
        monkeypatch.setattr(backend._provider, "_client", client)
        await run(cast(AgentService, app.state.operation_agent_service), "saved-before-exhaustion")
        assert len(calls) == 6
        service = cast(OperationChatService, app.state.operation_chat_service)
        gateway = cast(OpenAIConversationModel, service._model)
        parse = AsyncMock(side_effect=AssertionError("No real or fake paid dispatch is allowed"))
        monkeypatch.setattr(gateway._client.responses, "parse", parse)
        clock.value += timedelta(hours=7)
        topic = await service.create(
            "operator",
            TopicCreate(agent_id="retention-agent", product="mana", title="Saved MANA summary"),
        )
        payload = MessageCreate(request_id=uuid4(), message="Что известно об активности?")
        answer = await service.send("operator", topic.topic_id, payload)
        assert answer.status == "failed" and answer.next_action == "none"
        assert answer.model is None and answer.input_tokens is None
        assert "Последняя сохранённая сводка MANA" in answer.answer
        assert "2026-10-08T00:00:00+00:00" in answer.answer
        assert "давность: 7 ч 0 мин" in answer.answer
        assert "Данные устарели" in answer.answer
        assert "Mobile telemetry is unavailable" in answer.answer
        assert answer.sources[0].collected_at == datetime(2026, 10, 8, tzinfo=UTC)
        assert answer.sources[0].refresh_status == "stale"
        assert await service.send("operator", topic.topic_id, payload) == answer
        other = await service.create(
            "operator",
            TopicCreate(agent_id="retention-agent", product="360rec", title="360REC only"),
        )
        absent = await service.send(
            "operator", other.topic_id, MessageCreate(request_id=uuid4(), message="А тут?")
        )
        assert "сохранённой сводки для этого приложения пока нет" in absent.answer
        assert "children" not in absent.answer and absent.sources == []
        assert len(calls) == 6 and parse.call_count == 0
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "collected,expiry,status,expected",
    [
        ("2026-10-08T00:00:00+00:00", "2026-10-08T06:00:00+00:00", "live", "stale"),
        ("2026-10-08T01:00:00+00:00", "2026-10-08T08:00:00+00:00", "cached", "cached"),
        ("2026-10-08T09:00:00+00:00", "2026-10-08T15:00:00+00:00", "live", "unknown"),
        ("2026-10-08T01:00:00", "2026-10-08T08:00:00+00:00", "live", "unknown"),
        (None, None, "live", "unknown"),
        ("invalid", None, "live", "unknown"),
        ("2026-10-08T01:00:00+00:00", None, "stale", "stale"),
    ],
)
def test_report_creation_does_not_relabel_original_freshness(
    collected: str | None, expiry: str | None, status: str, expected: str
) -> None:
    now = datetime(2026, 10, 8, 7, tzinfo=UTC)
    report = AgentReport(
        report_id="fixture-report",
        run_id="fixture-run",
        agent_id="retention-agent",
        capability_key="retention.engagement.analyze",
        report_type="retention_engagement_analysis",
        period_start=now - timedelta(days=7),
        period_end=now,
        created_at=now,
        structured={
            "product": "360rec",
            "scope_verified": True,
            "scope_basis": "approved_source_binding",
            "collected_at": collected,
            "fresh_until": expiry,
            "refresh_status": status,
        },
        human_readable="Saved aggregate",
        data_quality_notes=[],
    )
    source = _report_source(report, now=now)
    assert source.refresh_status == expected
    assert source.created_at == now
    assert source.product == "360rec" and source.scope_verified
    if expected in {"cached", "stale"}:
        assert source.collected_at != source.created_at


def test_legacy_chat_sources_still_deserialize_without_inventing_freshness() -> None:
    from app.mana_operation_ai.domain.chat import ChatSource

    source = ChatSource(
        report_id="legacy",
        run_id="legacy-run",
        created_at=datetime(2026, 10, 8, tzinfo=UTC),
        title="Historical report",
    )
    assert source.collected_at is None and source.refresh_status == "unknown"
