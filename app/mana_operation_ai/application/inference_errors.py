"""Safe provider failure contracts; no SDK, upstream text or retry authority."""

from typing import Literal

InferenceFailureKind = Literal[
    "authentication",
    "permission",
    "quota",
    "rate_limit",
    "unavailable",
    "timeout",
    "connection",
    "invalid_request",
    "invalid_response",
    "unknown_usage",
]
InferencePendingStatus = Literal["queued", "in_progress"]


class InferenceProviderError(RuntimeError):
    def __init__(
        self,
        kind: InferenceFailureKind,
        *,
        http_status: int | None = None,
        pending_status: InferencePendingStatus | None = None,
    ) -> None:
        super().__init__(f"Inference provider failure: {kind}")
        self.kind = kind
        self.http_status = (
            http_status
            if http_status in {400, 401, 403, 404, 408, 409, 422, 429, 500, 502, 503, 504}
            else None
        )
        self.pending_status = (
            pending_status
            if kind == "unknown_usage"
            and type(pending_status) is str
            and pending_status in {"queued", "in_progress"}
            else None
        )


def inference_failure_message(failure: InferenceProviderError) -> str:
    messages: dict[InferenceFailureKind, str] = {
        "authentication": "AI-сервис отклонил ключ доступа. Нужна проверка конфигурации.",
        "permission": "AI-сервис отклонил доступ к выбранной модели. Нужна проверка прав.",
        "quota": "AI-сервис сообщил о лимите баланса или расходов. Нужна проверка аккаунта.",
        "rate_limit": "AI-сервис ограничил частоту запросов. Работа остановлена.",
        "unavailable": "AI-сервис временно недоступен. Работа остановлена.",
        "timeout": "AI-запрос не завершился вовремя. Исход запроса неизвестен.",
        "connection": "Связь с AI-сервисом прервалась. Исход запроса неизвестен.",
        "invalid_request": "AI-сервис отклонил параметры запроса. Нужна проверка интеграции.",
        "invalid_response": "Ответ AI не прошёл проверку. Его нельзя использовать как результат.",
        "unknown_usage": "Расходы AI-ответа не удалось проверить. Резерв сохранён.",
    }
    details = f" provider_status={failure.pending_status}." if failure.pending_status else ""
    return messages[failure.kind] + details + " История сохранена; автоматического повтора нет."
