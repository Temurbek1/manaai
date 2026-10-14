"""Strict private intent/row binding shared by persistence implementations."""

from pydantic import ValidationError

from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.domain.retention_contact import RetentionContactAction
from app.mana_operation_ai.infrastructure.persistence.models import RetentionContactRow


def contact_action(row: RetentionContactRow) -> RetentionContactAction:
    try:
        value = RetentionContactAction.model_validate(row.payload)
        if (value.action_id, value.owner, value.topic_id, value.status, value.revision) != (
            row.action_id,
            row.owner,
            row.topic_id,
            row.status,
            row.revision,
        ):
            raise ValueError("Private row binding changed")
        if row.request_id != str(value.request.request_id) or row.decision_id != (
            str(value.decision.request_id) if value.decision else None
        ):
            raise ValueError("Private request binding changed")
        return value
    except (ValidationError, ValueError):
        raise ChatError("Сохранённое контактное действие требует проверки.", 503) from None
