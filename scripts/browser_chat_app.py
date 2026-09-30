"""Local browser audit factory. Never contacts a model provider."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.main import create_app as create_real_app
from app.mana_operation_ai.application.chat_ports import ChatTurnOutput


class BrowserConversationFake:
    async def reply(self, *, instructions: str, context: str, owner: str) -> ChatTurnOutput:
        return ChatTurnOutput(
            "Это тестовый ответ. Сначала уточним цель, затем проверим сохранённые отчёты. "
            "Изменения не выполнялись. Привязка данных к приложению не подтверждена.",
            "browser-fake",
            10,
            20,
            next_action="approvals" if "Покажи предложения" in context else "none",
        )


def create_app() -> FastAPI:
    settings = get_settings()
    if (
        settings.app_env != "local"
        or settings.operation_ads_provider != "fake_meta"
        or settings.operation_product_activity_provider != "fake"
        or settings.operation_scheduler_enabled
        or settings.audio_moderation_enabled
        or settings.openai_api_key.get_secret_value() != "test-openai-key"
    ):
        raise RuntimeError("Browser harness requires isolated fake settings")
    app = create_real_app()
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def fake_lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with original_lifespan(application):
            application.state.operation_chat_service._model = BrowserConversationFake()
            yield

    app.router.lifespan_context = fake_lifespan
    return app
