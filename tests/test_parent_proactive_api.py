"""Before-first-message HTTP integration with actual private SQLite and fake providers."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from pytest import MonkeyPatch

from app import product_ai_main
from app.core.config import Settings, get_settings
from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt
from app.mana_ai.application.conversion import ConversionService
from app.mana_ai.application.parent_notifications import ParentPushUnknown
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.application.proactive_parent import ProactiveParentService
from app.mana_ai.domain.chat import ParentChildContext
from app.mana_ai.domain.conversion import ConversionPolicy
from app.mana_ai.domain.parent_notifications import ParentPushMessage, ParentPushReceipt
from app.mana_ai.domain.proactive_parent import ParentContactContext
from app.services import parent_chat_runtime as runtime_module
from app.services.proactive_parent_store import SqliteProactiveParentStore
from tests.test_child_safety_store import limits
from tests.test_conversion_agent import paid_offer, snapshot
from tests.test_family_agent_queue import intent
from tests.test_parent_chat import NOW, Children, Model
from tests.test_parent_chat_api import BACKEND_TOKEN, HEADERS

PREFIX = "/api/v1/mana-ai"


def contact(**changes: Any) -> ParentContactContext:
    return ParentContactContext.model_validate(
        {
            "parent_id": "123",
            "event_id": uuid4(),
            "revision": 1,
            "observed_at": NOW,
            "valid_until": NOW + timedelta(days=1),
            "language": "uz-Latn",
            "timezone": "Asia/Samarkand",
            "safety_chat_consent": True,
            "safety_push_consent": True,
            "marketing_push_consent": False,
        }
        | changes
    )


class Speaker(Model):
    async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        raw = await super().respond(prompt, max_output_tokens=max_output_tokens)
        return replace(
            raw,
            answer="Farzandingiz odatda qachon uxlaydi?",
            question_id=prompt.question.question_id if prompt.question else None,
        )


class Push:
    def __init__(self, devices: int = 1, *, unknown: bool = False) -> None:
        self.calls: list[ParentPushMessage] = []
        self.devices, self.unknown = devices, unknown

    async def send(self, message: ParentPushMessage) -> ParentPushReceipt:
        self.calls.append(message)
        if self.unknown:
            raise ParentPushUnknown("parent_push_outcome_unknown")
        return ParentPushReceipt(queued_devices=self.devices)


async def setup(
    tmp_path: Path,
) -> tuple[SqliteProactiveParentStore, ParentTouchService, Speaker, Children, Push]:
    store = SqliteProactiveParentStore(
        tmp_path / "family.db",
        conversion_policy=ConversionPolicy(),
        conversion_offers=(paid_offer(),),
        limits=limits(),
        daily_limit=2000,
        timezone="Asia/Samarkand",
    )
    await store.initialize()
    speaker, children, push = Speaker(), Children(), Push()
    service = ParentTouchService(
        store=store,
        children=children,
        model=speaker,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
        conversion=ConversionService(store, clock=lambda: NOW),
        proactive=ProactiveParentService(store, clock=lambda: NOW, gateway=push),
    )
    return store, service, speaker, children, push


async def test_before_first_parent_text_context_then_question_chat_then_push(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    store, service, model, children, push = await setup(tmp_path)
    settings = Settings(
        _env_file=None, openai_api_key=SecretStr("fake"), app_api_key=SecretStr(BACKEND_TOKEN)
    )
    monkeypatch.setattr(product_ai_main, "get_settings", lambda: settings)
    app = product_ai_main.create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.parent_chat_service = service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post(
                PREFIX + "/parent-touch/contact-context", json=contact().model_dump(mode="json")
            )
        ).status_code == 401
        preferences = contact()
        registered = await client.post(
            PREFIX + "/parent-touch/contact-context",
            headers=HEADERS,
            json=preferences.model_dump(mode="json"),
        )
        assert registered.status_code == 200 and registered.headers["Cache-Control"] == "no-store"
        assert (
            await client.get(
                PREFIX + "/parent-touch/contact-context?parent_id=456", headers=HEADERS
            )
        ).status_code == 404
        assert children.calls == model.calls == len(push.calls) == 0
        question = intent()
        queued = await client.post(
            PREFIX + "/parent-touch/requests",
            json=question.model_dump(mode="json"),
            headers=HEADERS,
        )
        assert queued.status_code == 201
        candidate = await store.next_delivery(NOW)
        assert candidate
        answer = await service.deliver(candidate)
        assert answer.asked_question
        assert model.prompts[0].response_language == "uz-Latn"
        assert children.calls == 2 and model.calls == 1 and not push.calls
        history = (
            await client.get(PREFIX + "/parent-touch/chat?parent_id=123", headers=HEADERS)
        ).json()
        assert [item["role"] for item in history["messages"]] == ["assistant"]
        assert history["messages"][0]["content"] == answer.answer
        assert await service.process_push()
        assert len(push.calls) == 1
        assert "uxlaydi" not in push.calls[0].description
        notifications = (
            await client.get(PREFIX + "/parent-touch/notifications?parent_id=123", headers=HEADERS)
        ).json()
        assert len(notifications["pushes"]) == 1
        saved = notifications["pushes"][0]
        assert saved["status"] == "queued_by_provider" and saved["queued_devices"] == 1
        assert saved["turn_id"] == history["messages"][0]["turn_id"]
        assert (
            await client.get(
                PREFIX + f"/parent-touch/notifications/{saved['push_id']}?parent_id=456",
                headers=HEADERS,
            )
        ).status_code == 404
        assert (await service.deliver(candidate)).answer == answer.answer
        assert await store.next_delivery(NOW) is None
        assert not await service.process_push()
        assert children.calls == 2 and model.calls == 1 and len(push.calls) == 1


@pytest.mark.parametrize(
    ("devices", "unknown", "status"), [(0, False, "not_queued"), (1, True, "unknown")]
)
async def test_missing_device_or_unknown_push_does_not_undo_or_repeat_chat(
    tmp_path: Path, devices: int, unknown: bool, status: str
) -> None:
    store, touch, model, children, push = await setup(tmp_path)
    push.devices, push.unknown = devices, unknown
    assert touch.proactive
    await touch.proactive.register(contact())
    await touch.request_question(intent())
    candidate = await store.next_delivery(NOW)
    assert candidate
    await touch.deliver(candidate)
    assert await touch.process_push()
    assert not await touch.process_push()
    assert len((await touch.read_touch_history("123", before=None, limit=20)).messages) == 1
    assert (await store.pushes("123", after=0, limit=20)).pushes[0].status == status
    assert len(push.calls) == 1 and children.calls == 2 and model.calls == 1


async def test_conversion_first_contact_push_needs_separate_marketing_permission(
    tmp_path: Path,
) -> None:
    store, touch, model, children, push = await setup(tmp_path)
    assert touch.proactive and touch.conversion
    await touch.proactive.register(contact(marketing_push_consent=True))
    await touch.conversion.observe(snapshot())
    assert await touch.process_conversion()
    assert await touch.process_push()
    assert model.calls == children.calls == 0 and len(push.calls) == 1
    assert (await store.pushes("123", after=0, limit=20)).pushes[0].purpose == "marketing"


async def test_actual_lifespan_worker_proactive_contact_and_v8_deactivation(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    class CurrentChildren(Children):
        async def read(self, parent_id: str) -> ParentChildContext:
            return (await super().read(parent_id)).model_copy(
                update={"collected_at": datetime.now(UTC)}
            )

    class ClosableSpeaker(Speaker):
        async def close(self) -> None:
            pass

    class UnusedSafety:
        async def close(self) -> None:
            pass

    class NotifyingPush(Push):
        def __init__(self) -> None:
            super().__init__()
            self.sent = asyncio.Event()

        async def send(self, message: ParentPushMessage) -> ParentPushReceipt:
            result = await super().send(message)
            self.sent.set()
            return result

    speaker, children, push = ClosableSpeaker(), CurrentChildren(), NotifyingPush()
    monkeypatch.setattr(runtime_module, "OpenAIParentChatModel", lambda config: speaker)
    monkeypatch.setattr(runtime_module, "OpenAIChildSafetyModel", lambda config: UnusedSafety())
    monkeypatch.setattr(runtime_module, "ManakidsChatChildrenSource", lambda **kwargs: children)
    monkeypatch.setattr(runtime_module, "ManakidsParentPushGateway", lambda **kwargs: push)
    config = Settings(
        _env_file=None,
        openai_api_key=SecretStr("synthetic-only"),
        app_api_key=SecretStr(BACKEND_TOKEN),
        mana_parent_chat_enabled=True,
        mana_parent_touch_enabled=True,
        mana_parent_chat_database_path=tmp_path / "lifespan.db",
        mana_parent_touch_review_first_enabled=True,
        mana_child_safety_enabled=True,
        mana_child_safety_limits=limits(
            job_tokens=2000, parent_daily_tokens=2000, server_daily_tokens=2000
        ),
        mana_parent_touch_proactive_enabled=True,
        mana_parent_push_enabled=True,
        mana_child_safety_poll_seconds=0.05,
        manakids_api_username="synthetic",
        manakids_api_password=SecretStr("synthetic"),
    )
    async with runtime_module.parent_chat_runtime(config) as service:
        assert isinstance(service, ParentTouchService) and service.proactive
        now = datetime.now(UTC)
        await service.proactive.register(
            contact(observed_at=now, valid_until=now + timedelta(hours=1))
        )
        await service.request_question(
            intent().model_copy(update={"observed_at": now, "expires_at": now + timedelta(hours=1)})
        )
        await asyncio.wait_for(push.sent.wait(), timeout=3)
        history = await service.read_touch_history("123", before=None, limit=20)
        assert [message.role for message in history.messages] == ["assistant"]
        assert speaker.prompts[0].response_language == "uz-Latn"
        assert len(push.calls) == speaker.calls == 1 and children.calls == 2
    closed = config.model_copy(
        update={
            "mana_parent_touch_proactive_enabled": False,
            "mana_parent_push_enabled": False,
            "mana_child_safety_enabled": False,
            "mana_parent_touch_review_first_enabled": False,
        }
    )
    async with runtime_module.parent_chat_runtime(closed) as service:
        assert isinstance(service, ParentTouchService) and service.proactive is None
        assert (
            await service.read_touch_history("123", before=None, limit=20)
        ).messages == history.messages
        assert not await service.process_push()
    assert len(push.calls) == speaker.calls == 1 and children.calls == 2
