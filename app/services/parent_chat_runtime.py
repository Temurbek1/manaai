from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx

from app.core.config import Settings
from app.mana_ai.application.child_safety import ChildSafetyService
from app.mana_ai.application.parent_chat import ParentChatService
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.application.reviewed_message_ports import ReviewedMessageStore
from app.services.child_safety_model import OpenAIChildSafetyModel
from app.services.child_safety_prompts import ChildSafetyPromptBuilder
from app.services.child_safety_store import SqliteChildSafetyStore
from app.services.family_agent_store import SqliteFamilyAgentStore
from app.services.family_agent_worker import FamilyAgentWorker
from app.services.family_compatibility_store import (
    SqliteClosedSafetyBrokerStore,
    SqliteFamilyCompatibilityStore,
    family_storage_version,
)
from app.services.mana_ai_openai_gateway import SystemManaAIClock
from app.services.parent_chat_children import ManakidsChatChildrenSource
from app.services.parent_chat_model import OpenAIParentChatModel
from app.services.parent_chat_store import SqliteParentChatStore
from app.services.reviewed_message_store import (
    SqliteClosedReviewedBrokerStore,
    SqliteReviewedMessageStore,
)


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
    version = await family_storage_version(settings.mana_parent_chat_database_path)
    reviewed: ReviewedMessageStore | None = None
    if settings.mana_parent_touch_review_first_enabled:
        assert settings.mana_child_safety_limits is not None
        review_store = SqliteReviewedMessageStore(
            settings.mana_parent_chat_database_path,
            limits=settings.mana_child_safety_limits,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            **store_arguments,
        )
        store, reviewed = review_store, review_store
    elif version == 6 and settings.mana_child_safety_enabled:
        raise RuntimeError("V6 safety execution requires the captured review-first runtime")
    elif version == 6 and settings.mana_parent_touch_enabled:
        closed_review_store = SqliteClosedReviewedBrokerStore(
            settings.mana_parent_chat_database_path,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            **store_arguments,
        )
        store, reviewed = closed_review_store, closed_review_store
    elif settings.mana_child_safety_enabled:
        assert settings.mana_child_safety_limits is not None
        store = SqliteChildSafetyStore(
            settings.mana_parent_chat_database_path,
            limits=settings.mana_child_safety_limits,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            **store_arguments,
        )
    elif settings.mana_parent_touch_enabled and version == 5:
        store = SqliteClosedSafetyBrokerStore(
            settings.mana_parent_chat_database_path,
            timezone=settings.mana_parent_chat_timezone,
            question_limit=settings.mana_parent_touch_question_limit,
            **store_arguments,
        )
    elif version >= 2 and (not settings.mana_parent_touch_enabled or version >= 4):
        store = SqliteFamilyCompatibilityStore(
            settings.mana_parent_chat_database_path,
            version=version,
            history_only=not settings.mana_parent_touch_enabled,
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
        touch_settings = (
            settings.model_copy(update={"openai_model": settings.mana_parent_touch_model})
            if settings.mana_parent_touch_enabled and settings.mana_parent_touch_model
            else settings
        )
        model = OpenAIParentChatModel(touch_settings)
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
            if isinstance(store, SqliteFamilyAgentStore) and settings.mana_parent_touch_enabled:
                safety = None
                if isinstance(store, SqliteChildSafetyStore):
                    assert settings.mana_child_safety_limits is not None
                    safety_settings = (
                        settings.model_copy(
                            update={"openai_model": settings.mana_child_safety_model}
                        )
                        if settings.mana_child_safety_model
                        else settings
                    )
                    safety_model = OpenAIChildSafetyModel(safety_settings)
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
                    reviewed=reviewed,
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
