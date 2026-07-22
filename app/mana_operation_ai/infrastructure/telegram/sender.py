import asyncio
import json
import os
from pathlib import Path

import httpx

from app.mana_operation_ai.application.auth_ports import (
    TelegramDeliveryError,
    TelegramDeliveryFailure,
)


class TelegramBotOtpSender:
    def __init__(
        self,
        *,
        bot_token: str,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._endpoint = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._timeout = timeout_seconds
        self._transport = transport

    async def send_login_code(self, *, telegram_id: int, code: str, ttl_seconds: int) -> None:
        payload = {
            "chat_id": telegram_id,
            "text": (
                f"Код входа в MANA: {code}\n"
                f"Код действует {ttl_seconds} секунд и может быть использован один раз.\n"
                "Никому не сообщайте этот код."
            ),
            "disable_web_page_preview": True,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.post(self._endpoint, json=payload)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TelegramDeliveryError(TelegramDeliveryFailure.TRANSIENT) from exc
        if response.is_success:
            return
        failure = _classify_failure(response)
        raise TelegramDeliveryError(failure)


class UnavailableTelegramOtpSender:
    async def send_login_code(self, *, telegram_id: int, code: str, ttl_seconds: int) -> None:
        del telegram_id, code, ttl_seconds
        raise TelegramDeliveryError(TelegramDeliveryFailure.UNAVAILABLE)


class FileTelegramOtpSender:
    """Explicit local-test sink; never selected unless test mode is enabled."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    async def send_login_code(self, *, telegram_id: int, code: str, ttl_seconds: int) -> None:
        record = json.dumps(
            {
                "telegram_id": telegram_id,
                "code": code,
                "ttl_seconds": ttl_seconds,
            },
            separators=(",", ":"),
        )
        async with self._lock:
            await asyncio.to_thread(self._append, record)

    def _append(self, record: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self._path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            os.write(descriptor, f"{record}\n".encode())
        finally:
            os.close(descriptor)


def _classify_failure(response: httpx.Response) -> TelegramDeliveryFailure:
    if response.status_code >= 500 or response.status_code == 429:
        return TelegramDeliveryFailure.TRANSIENT
    description = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            raw_description = body.get("description")
            if isinstance(raw_description, str):
                description = raw_description.casefold()
    except ValueError:
        pass
    bot_not_started_markers = (
        "chat not found",
        "bot was blocked",
        "user is deactivated",
        "bot can't initiate conversation",
    )
    if response.status_code in {400, 403} and any(
        marker in description for marker in bot_not_started_markers
    ):
        return TelegramDeliveryFailure.BOT_NOT_STARTED
    return TelegramDeliveryFailure.PERMANENT
