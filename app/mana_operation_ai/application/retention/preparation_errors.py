"""Only closed host-owned preparation failures may change client recovery behavior."""

from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.domain.contact_admission import PreparationFailureCode

_FAILURES: dict[PreparationFailureCode, tuple[int, str]] = {
    "contact_preparation_stopped": (423, "Подготовка контактных действий Retention остановлена."),
    "contact_preparation_pending": (
        409,
        "Подготовка уже начата; результат пока не подтверждён. Чтение не повторялось.",
    ),
    "contact_preparation_limit": (429, "Достигнут лимит подготовки. Новое чтение не начиналось."),
    "contact_preparation_conflict": (409, "Запрос подготовки уже связан с другими параметрами."),
    "contact_preparation_history_unavailable": (
        503,
        "История допуска требует проверки. Новое чтение не начиналось.",
    ),
}


class ContactPreparationError(ChatError):
    def __init__(self, code: PreparationFailureCode) -> None:
        status, message = _FAILURES[code]
        super().__init__(message, status)
        self.code = code
