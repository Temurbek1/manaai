from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx

from app.core.config import Settings
from app.mana_ai.application.parent_chat import ParentChatService
from app.services.parent_chat_children import ManakidsChatChildrenSource
from app.services.parent_chat_model import OpenAIParentChatModel
from app.services.parent_chat_store import SqliteParentChatStore


@asynccontextmanager
async def parent_chat_runtime(settings: Settings) -> AsyncIterator[ParentChatService | None]:
    if not settings.mana_parent_chat_enabled:
        yield None
        return
    assert settings.manakids_api_username and settings.manakids_api_password
    store = SqliteParentChatStore(
        settings.mana_parent_chat_database_path,
        daily_limit=settings.mana_parent_chat_daily_tokens,
        timezone=settings.mana_parent_chat_timezone,
        max_attempts=settings.mana_parent_chat_max_attempts_per_day,
    )
    await store.initialize()
    async with httpx.AsyncClient(
        timeout=15, follow_redirects=False, transport=httpx.AsyncHTTPTransport(retries=0)
    ) as client:
        model = OpenAIParentChatModel(settings)
        try:
            yield ParentChatService(
                store=store,
                children=ManakidsChatChildrenSource(
                    client=client,
                    base_url=settings.manakids_api_base_url,
                    username=settings.manakids_api_username,
                    password=settings.manakids_api_password.get_secret_value(),
                    wall_timeout_seconds=settings.mana_parent_chat_source_timeout_seconds,
                ),
                model=model,
                clock=lambda: datetime.now(UTC),
                max_output_tokens=settings.mana_parent_chat_max_output_tokens,
                history_turn_limit=settings.mana_parent_chat_history_turns,
            )
        finally:
            await model.close()
