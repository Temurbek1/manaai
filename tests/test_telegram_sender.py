import json

import httpx
import pytest

from app.mana_operation_ai.application.auth_ports import (
    TelegramDeliveryError,
    TelegramDeliveryFailure,
)
from app.mana_operation_ai.infrastructure.telegram.sender import TelegramBotOtpSender

TEST_TOKEN = "test-telegram-token-sensitive"


async def test_telegram_sender_translates_success_at_the_adapter_boundary() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True}, request=request)

    sender = TelegramBotOtpSender(
        bot_token=TEST_TOKEN,
        transport=httpx.MockTransport(handler),
    )
    await sender.send_login_code(telegram_id=976835256, code="123456", ttl_seconds=60)
    assert captured["chat_id"] == 976835256
    assert "123456" in str(captured["text"])
    assert "60" in str(captured["text"])


@pytest.mark.parametrize(
    ("status_code", "description", "expected"),
    [
        (403, "Forbidden: bot was blocked by the user", TelegramDeliveryFailure.BOT_NOT_STARTED),
        (400, "Bad Request: chat not found", TelegramDeliveryFailure.BOT_NOT_STARTED),
        (429, "Too Many Requests", TelegramDeliveryFailure.TRANSIENT),
        (500, "Internal Server Error", TelegramDeliveryFailure.TRANSIENT),
        (400, "Bad Request: invalid chat", TelegramDeliveryFailure.PERMANENT),
    ],
)
async def test_telegram_sender_sanitizes_provider_failures(
    status_code: int,
    description: str,
    expected: TelegramDeliveryFailure,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"ok": False, "description": description},
            request=request,
        )

    sender = TelegramBotOtpSender(
        bot_token=TEST_TOKEN,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(TelegramDeliveryError) as failure:
        await sender.send_login_code(telegram_id=976835256, code="654321", ttl_seconds=60)
    assert failure.value.failure is expected
    assert TEST_TOKEN not in str(failure.value)
    assert "654321" not in str(failure.value)


async def test_telegram_sender_sanitizes_network_errors() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("test connection failed", request=request)

    sender = TelegramBotOtpSender(
        bot_token=TEST_TOKEN,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(TelegramDeliveryError) as failure:
        await sender.send_login_code(telegram_id=976835256, code="654321", ttl_seconds=60)
    assert failure.value.failure is TelegramDeliveryFailure.TRANSIENT
    assert TEST_TOKEN not in str(failure.value)
