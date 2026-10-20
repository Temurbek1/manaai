from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx

from app.core.config import Settings
from app.mana_ai.application.child_safety import ChildSafetyService
from app.mana_ai.application.parent_chat import ParentChatService
from app.mana_ai.application.parent_touch import ParentTouchService
from app.services.child_safety_model import OpenAIChildSafetyModel
from app.services.child_safety_prompts import ChildSafetyPromptBuilder
from app.services.child_safety_store import SqliteChildSafetyStore
from app.services.family_agent_store import SqliteFamilyAgentStore
from app.services.family_agent_worker import FamilyAgentWorker
from app.services.mana_ai_openai_gateway import SystemManaAIClock
from app.services.parent_chat_children import ManakidsChatChildrenSource
from app.services.parent_chat_model import OpenAIParentChatModel
from app.services.parent_chat_store import SqliteParentChatStore


@asynccontextmanager
async def parent_chat_runtime(settings: Settings) -> AsyncIterator[ParentChatService | None]:
    if not settings.mana_parent_chat_enabled:
        yield None
        return
    assert settings.manakids_api_username and settings.manakids_api_password
    store: SqliteParentChatStore
    store_arguments = {
        "daily_limit": settings.mana_parent_chat_daily_tokens,
        "max_attempts": settings.mana_parent_chat_max_attempts_per_day,
    }
    if settings.mana_child_safety_enabled:
        assert settings.mana_child_safety_limits is not None
        store = SqliteChildSafetyStore(
            settings.mana_parent_chat_database_path,
            limits=settings.mana_child_safety_limits,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            **store_arguments,
        )
    elif settings.mana_parent_touch_enabled:
        store = SqliteFamilyAgentStore(
            settings.mana_parent_chat_database_path,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            **store_arguments,
        )
    else:
        store = SqliteParentChatStore(
            settings.mana_parent_chat_database_path,
            timezone=settings.mana_parent_chat_timezone,
            **store_arguments,
        )
    await store.initialize()
    async with httpx.AsyncClient(
        timeout=15, follow_redirects=False, transport=httpx.AsyncHTTPTransport(retries=0)
    ) as client:
        model = OpenAIParentChatModel(settings)
        safety_model: OpenAIChildSafetyModel | None = None
        worker: FamilyAgentWorker | None = None
        try:
            children = ManakidsChatChildrenSource(
                client=client,
                base_url=settings.manakids_api_base_url,
                username=settings.manakids_api_username,
                password=settings.manakids_api_password.get_secret_value(),
                wall_timeout_seconds=settings.mana_parent_chat_source_timeout_seconds,
            )
            if isinstance(store, SqliteFamilyAgentStore):
                safety = None
                if isinstance(store, SqliteChildSafetyStore):
                    assert settings.mana_child_safety_limits is not None
                    safety_model = OpenAIChildSafetyModel(settings)
                    safety = ChildSafetyService(
                        store=store,
                        children=children,
                        model=safety_model,
                        prompts=ChildSafetyPromptBuilder(),
                        clock=SystemManaAIClock(),
                        limits=settings.mana_child_safety_limits,
                        max_output_tokens=settings.mana_child_safety_max_output_tokens,
                    )
                service: ParentChatService = ParentTouchService(
                    store=store,
                    children=children,
                    model=model,
                    clock=lambda: datetime.now(UTC),
                    max_output_tokens=settings.mana_parent_chat_max_output_tokens,
                    history_turn_limit=settings.mana_parent_chat_history_turns,
                    safety=safety,
                )
                if safety is not None:
                    assert isinstance(service, ParentTouchService)
                    worker = FamilyAgentWorker(
                        safety,
                        service,
                        clock=lambda: datetime.now(UTC),
                        interval=settings.mana_child_safety_poll_seconds,
                    )
                    worker.start()
            else:
                service = ParentChatService(
                    store=store,
                    children=children,
                    model=model,
                    clock=lambda: datetime.now(UTC),
                    max_output_tokens=settings.mana_parent_chat_max_output_tokens,
                    history_turn_limit=settings.mana_parent_chat_history_turns,
                )
            yield service
        finally:
            if worker is not None:
                await worker.close()
            if safety_model is not None:
                await safety_model.close()
            await model.close()
