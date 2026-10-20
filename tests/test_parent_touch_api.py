import asyncio
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from pytest import MonkeyPatch

from app import product_ai_main
from app.core.config import Settings, get_settings
from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.chat import ParentChildContext
from app.mana_ai.domain.family_agents import ParentTouchDeliveryRequest
from app.services import parent_chat_runtime as runtime_module
from tests.test_family_agent_queue import intent, store
from tests.test_parent_chat import NOW, Children, Model, message
from tests.test_parent_chat_api import BACKEND_TOKEN, HEADERS

PREFIX = "/api/v1/mana-ai"


class TouchModel(Model):
    defer = False

    async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        raw = await super().respond(prompt, max_output_tokens=max_output_tokens)
        question = prompt.question if not self.defer else None
        return replace(
            raw,
            answer="Tushunarli." + (" Farzandingiz qachon uxlaydi?" if question else ""),
            question_id=question.question_id if question else None,
        )

    async def close(self) -> None:
        pass


async def test_http_single_chat_question_answer_queue_and_frozen_replay(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configuration = Settings(
        _env_file=None,
        openai_api_key=SecretStr("unit-openai"),
        app_api_key=SecretStr(BACKEND_TOKEN),
    )
    monkeypatch.setattr(product_ai_main, "get_settings", lambda: configuration)
    repository = await store(tmp_path / "family.db")
    model, children = TouchModel(), Children()
    service = ParentTouchService(
        store=repository,
        model=model,
        children=children,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    app = product_ai_main.create_app()
    app.dependency_overrides[get_settings] = lambda: configuration
    app.state.parent_chat_service = service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for path in (
            "/agents",
            "/parent-touch/chat?parent_id=123",
            "/parent-touch/requests?parent_id=123",
        ):
            assert (await client.get(PREFIX + path)).status_code == 401
            read = await client.get(PREFIX + path, headers=HEADERS)
            assert read.status_code == 200 and read.headers["Cache-Control"] == "no-store"
        assert children.calls == model.calls == 0
        agents = (await client.get(PREFIX + "/agents", headers=HEADERS)).json()["agents"]
        assert [(a["definition"]["agent_id"], a["status"]) for a in agents] == [
            ("parent-touch", "available"),
            ("child-safety", "disabled"),
        ]
        initial = message(text="Salom").model_dump(mode="json")
        old = await client.post(PREFIX + "/chat", json=initial, headers=HEADERS)
        same = await client.post(PREFIX + "/parent-touch/chat", json=initial, headers=HEADERS)
        assert old.status_code == same.status_code == 200
        assert same.json()["answer"] == old.json()["answer"]
        assert same.json()["asked_question"] is None
        assert children.calls == model.calls == 1

        source = intent()
        first = await client.post(
            PREFIX + "/parent-touch/requests",
            json=source.model_dump(mode="json"),
            headers=HEADERS,
        )
        assert first.status_code == 201
        question_id = first.json()["question"]["question_id"]
        source_calls = children.calls
        duplicate = await client.post(
            PREFIX + "/parent-touch/requests",
            json=source.model_copy(update={"request_id": uuid4()}).model_dump(mode="json"),
            headers=HEADERS,
        )
        assert duplicate.status_code == 201 and duplicate.json()["coalesced"]
        assert children.calls == source_calls and model.calls == 1
        await service.request_question(intent("school.schedule"))
        delivery = {"parent_id": "123", "request_id": str(uuid4())}
        delivered = await client.post(
            PREFIX + "/parent-touch/deliver", json=delivery, headers=HEADERS
        )
        assert delivered.status_code == 200 and delivered.json()["speaker"] == "parent-touch"
        assert delivered.json()["asked_question"]["question_id"] == question_id
        assert model.prompts[-1].response_language == "uz-Latn"
        assert (
            await repository.language_reference(
                "123", delivered.json()["asked_question"]["turn_id"]
            )
            == "Salom"
        )
        assert all(content for role, content in model.prompts[-1].messages if role == "user")
        assert "not a new parent message" in model.prompts[-1].instructions
        counts = children.calls, model.calls
        replay = await client.post(PREFIX + "/parent-touch/deliver", json=delivery, headers=HEADERS)
        assert replay.json() == delivered.json() and (children.calls, model.calls) == counts
        conflict = await client.post(
            PREFIX + "/parent-touch/deliver",
            json=delivery | {"request_id": str(uuid4())},
            headers=HEADERS,
        )
        assert conflict.status_code == 409 and (children.calls, model.calls) == counts
        history = (
            await client.get(PREFIX + "/parent-touch/chat?parent_id=123", headers=HEADERS)
        ).json()
        assert [m["role"] for m in history["messages"]] == ["user", "assistant", "assistant"]
        assert history["active_question"] == delivered.json()["asked_question"]
        assert history["message_questions"] == [history["active_question"]]
        assert (children.calls, model.calls) == counts

        reply = message(text="Soat to'qqizda.").model_dump(mode="json") | {
            "reply_to_question_id": question_id
        }
        answered = await client.post(PREFIX + "/parent-touch/chat", json=reply, headers=HEADERS)
        assert answered.status_code == 200
        next_id = answered.json()["asked_question"]["question_id"]
        assert next_id != question_id
        counts = children.calls, model.calls
        original_replay = await client.post(
            PREFIX + "/parent-touch/deliver", json=delivery, headers=HEADERS
        )
        assert original_replay.json() == delivered.json()
        stale = await client.post(
            PREFIX + "/parent-touch/chat",
            json=reply | {"request_id": str(uuid4())},
            headers=HEADERS,
        )
        assert stale.status_code == 409 and (children.calls, model.calls) == counts
        # A changed nonce/body after answering the same revision cannot ask it again.
        terminal = await client.post(
            PREFIX + "/parent-touch/requests",
            json=source.model_copy(
                update={"request_id": uuid4(), "question": "Reworded?"}
            ).model_dump(mode="json"),
            headers=HEADERS,
        )
        assert terminal.status_code == 201 and terminal.json()["question"]["status"] == "answered"
        assert (children.calls, model.calls) == counts
        foreign = await client.get(PREFIX + "/parent-touch/chat?parent_id=456", headers=HEADERS)
        assert foreign.json()["messages"] == [] and foreign.json()["active_question"] is None
        invalid = await client.post(
            PREFIX + "/parent-touch/chat",
            json=reply | {"chat_id": "another"},
            headers=HEADERS,
        )
        assert invalid.status_code == 422 and (children.calls, model.calls) == counts


async def test_failed_intent_and_nonce_alias_never_repeat_source_reads(tmp_path: Path) -> None:
    class FailingChildren(Children):
        async def read(self, parent_id: str) -> ParentChildContext:
            self.calls += 1
            raise ParentChatError("synthetic_source_failure", 503)

    repository, children, model = (
        await store(tmp_path / "failure.db"),
        FailingChildren(),
        TouchModel(),
    )
    service = ParentTouchService(
        store=repository,
        children=children,
        model=model,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    source = intent()
    for request in (source, source.model_copy(update={"request_id": uuid4()})):
        with pytest.raises(ParentChatError, match="synthetic_source_failure"):
            await service.request_question(request)
    assert children.calls == 1 and model.calls == 0
    with pytest.raises(ParentChatError, match="request_id_conflict"):
        await service.request_question(source.model_copy(update={"question": "Different?"}))
    with pytest.raises(ParentChatError, match="specialist_not_registered"):
        await service.request_question(intent(agent="not-registered"))
    assert children.calls == 1


async def test_racing_new_nonces_share_one_durable_intent_claim(tmp_path: Path) -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    class PausedChildren(Children):
        async def read(self, parent_id: str) -> ParentChildContext:
            entered.set()
            await release.wait()
            return await super().read(parent_id)

    path = tmp_path / "race.db"
    children, model = PausedChildren(), TouchModel()
    first = ParentTouchService(
        store=await store(path),
        children=children,
        model=model,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    second = ParentTouchService(
        store=await store(path),
        children=children,
        model=model,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    source = intent()
    task = asyncio.create_task(first.request_question(source))
    await entered.wait()
    alias = source.model_copy(update={"request_id": uuid4()})
    with pytest.raises(ParentChatError, match="intent_already_admitted"):
        await second.request_question(alias)
    release.set()
    original = await task
    duplicate = await second.request_question(alias)
    assert duplicate.question == original.question and duplicate.coalesced
    assert children.calls == 1
    with pytest.raises(ParentChatError, match="request_id_conflict"):
        await second.request_question(alias.model_copy(update={"reason": "Changed"}))


async def test_delivery_requires_parent_language_and_cannot_repeat_a_deferred_context(
    tmp_path: Path,
) -> None:
    repository, model, children = await store(tmp_path / "delivery.db"), TouchModel(), Children()
    service = ParentTouchService(
        store=repository,
        children=children,
        model=model,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    await repository.enqueue(intent(), NOW)
    request = ParentTouchDeliveryRequest(parent_id="123", request_id=uuid4())
    with pytest.raises(ParentChatError, match="parent_language_not_established"):
        await service.deliver(request)
    assert children.calls == model.calls == 0
    model.defer = True
    await service.send(message(text="Salom"))
    result = await service.deliver(request)
    assert result.asked_question is None
    counts = children.calls, model.calls
    with pytest.raises(ParentChatError, match="delivery_context_already_processed"):
        await service.deliver(request.model_copy(update={"request_id": uuid4()}))
    assert (children.calls, model.calls) == counts
    assert await service.deliver(request) == result
    # New parent text is a different context, not a retry of the old delivery.
    await service.send(message(text="Yangi xabar"))
    await service.deliver(request.model_copy(update={"request_id": uuid4()}))
    assert model.calls == counts[1] + 2


async def test_runtime_flag_routes_shared_store_and_durable_replay_across_restart(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configuration = Settings(
        _env_file=None,
        openai_api_key=SecretStr("unit-openai"),
        app_api_key=SecretStr(BACKEND_TOKEN),
        mana_parent_chat_enabled=True,
        mana_parent_touch_enabled=True,
        mana_parent_chat_database_path=tmp_path / "runtime.db",
        manakids_api_username="unit-backend",
        manakids_api_password=SecretStr("unit-secret"),
    )
    model, children = TouchModel(), Children()
    monkeypatch.setattr(runtime_module, "OpenAIParentChatModel", lambda settings: model)
    monkeypatch.setattr(runtime_module, "ManakidsChatChildrenSource", lambda **kwargs: children)
    request = message()
    for _ in range(2):
        async with runtime_module.parent_chat_runtime(configuration) as service:
            assert isinstance(service, ParentTouchService)
            result = await service.send(request)
            assert result.answer == "Tushunarli."
            assert (
                await service.read_touch_history("123", before=None, limit=30)
            ).quota.used_tokens == 150
    assert model.calls == children.calls == 1
    assert model.prompts[0].structured_reply


def test_parent_touch_requires_parent_chat_and_is_default_disabled() -> None:
    assert not Settings(_env_file=None, openai_api_key=SecretStr("unit")).mana_parent_touch_enabled
    with pytest.raises(ValidationError, match="isolated parent chat"):
        Settings(_env_file=None, openai_api_key=SecretStr("unit"), mana_parent_touch_enabled=True)


async def test_expired_intent_is_rejected_before_source_and_remains_rejected(
    tmp_path: Path,
) -> None:
    repository, model, children = await store(tmp_path / "expired.db"), TouchModel(), Children()
    service = ParentTouchService(
        store=repository,
        children=children,
        model=model,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    request = intent().model_copy(
        update={"observed_at": NOW - timedelta(days=3), "expires_at": NOW - timedelta(days=1)}
    )
    for _ in range(2):
        with pytest.raises(ParentChatError, match="question_outside_observation_window"):
            await service.request_question(request)
    assert children.calls == model.calls == 0


async def test_unknown_delivery_holds_question_and_quota_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "unknown.db"
    repository, model, children = await store(path), TouchModel(), Children()
    service = ParentTouchService(
        store=repository,
        children=children,
        model=model,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    await service.send(message(text="Здравствуйте"))
    await service.request_question(intent())
    model.error = TimeoutError("Synthetic lost receipt")
    delivery = ParentTouchDeliveryRequest(parent_id="123", request_id=uuid4())
    with pytest.raises(ParentChatError, match="model_receipt_unknown"):
        await service.deliver(delivery)
    counts = children.calls, model.calls
    replacement = ParentTouchService(
        store=await store(path),
        children=children,
        model=model,
        clock=lambda: NOW + timedelta(days=1),
        max_output_tokens=512,
        history_turn_limit=2,
    )
    for request in (delivery, delivery.model_copy(update={"request_id": uuid4()})):
        with pytest.raises(ParentChatError):
            await replacement.deliver(request)
    history = await replacement.read_touch_history("123", before=None, limit=30)
    assert history.quota.blocked_by_unresolved_request
    assert [m.role for m in history.messages] == ["user", "assistant"]
    assert history.active_question is None
    assert (await repository.questions("123")).questions[0].status == "held"
    assert (children.calls, model.calls) == counts


async def test_intent_ownership_failure_is_durable_and_future_revision_is_new(
    tmp_path: Path,
) -> None:
    from app.mana_ai.domain.family_agents import ParentTouchRequest

    repository, model, children = await store(tmp_path / "ownership.db"), TouchModel(), Children()
    service = ParentTouchService(
        store=repository,
        children=children,
        model=model,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    bad = intent(child=999)
    for request in (bad, bad.model_copy(update={"request_id": uuid4()})):
        with pytest.raises(ParentChatError, match="question_child_not_authorized"):
            await service.request_question(request)
    assert children.calls == 1 and model.calls == 0
    original = intent()
    first = await service.request_question(original)
    await service.send(message())
    await service.send(
        ParentTouchRequest(
            parent_id="123",
            request_id=uuid4(),
            message="В девять.",
            reply_to_question_id=first.question.question_id,
        )
    )
    changed = await service.request_question(
        original.model_copy(
            update={
                "request_id": uuid4(),
                "source_revision": "new-observation",
            }
        )
    )
    assert changed.question.question_id != first.question.question_id
    assert changed.question.status == "queued"


async def test_disabled_family_endpoints_never_bootstrap_the_runtime(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configuration = Settings(
        _env_file=None,
        openai_api_key=SecretStr("unit-openai"),
        app_api_key=SecretStr(BACKEND_TOKEN),
        mana_parent_chat_database_path=tmp_path / "absent.db",
    )
    monkeypatch.setattr(product_ai_main, "get_settings", lambda: configuration)
    app = product_ai_main.create_app()
    app.dependency_overrides[get_settings] = lambda: configuration
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        for path in (
            "/agents",
            "/parent-touch/chat?parent_id=123",
            "/parent-touch/requests?parent_id=123",
        ):
            response = await client.get(PREFIX + path, headers=HEADERS)
            assert response.status_code == 503
            assert response.json()["detail"] == {"code": "parent_touch_disabled"}
    assert not configuration.mana_parent_chat_database_path.exists()
