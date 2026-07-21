from pathlib import Path

from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app
from app.schemas.ai import ChatRequest, ChatResponse, SummarizeRequest, SummarizeResponse


def configure_test_env(monkeypatch: MonkeyPatch, database_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("APP_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MARKETING_DATABASE_PATH", str(database_path))
    get_settings.cache_clear()


class FakeOpenAIService:
    async def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(answer=f"echo: {request.message}", model="fake-model")

    async def summarize(self, request: SummarizeRequest) -> SummarizeResponse:
        return SummarizeResponse(summary=request.text[:16], model="fake-model")


async def test_chat_endpoint(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    app = create_app()

    async with app.router.lifespan_context(app):
        app.state.openai_service = FakeOpenAIService()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post("/api/v1/ai/chat", json={"message": "hello"})

    assert response.status_code == 200
    assert response.json() == {"answer": "echo: hello", "model": "fake-model"}
    get_settings.cache_clear()


async def test_summarize_endpoint(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    app = create_app()

    async with app.router.lifespan_context(app):
        app.state.openai_service = FakeOpenAIService()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/v1/ai/summarize",
                json={"text": "A long text for summarization.", "max_sentences": 2},
            )

    assert response.status_code == 200
    assert response.json() == {"summary": "A long text for ", "model": "fake-model"}
    get_settings.cache_clear()
