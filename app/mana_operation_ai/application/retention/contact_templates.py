"""Versioned immutable texts. Changing a text requires a new template version."""

import hashlib
import json
from types import MappingProxyType

from app.mana_operation_ai.domain.retention_contact import (
    RetentionContactMessage,
    RetentionContactParameters,
)

_TEXTS = MappingProxyType(
    {
        (
            "ru",
            "onboarding_help",
        ): "MANA: нужна помощь с настройкой? Откройте раздел помощи в приложении.",
        (
            "ru",
            "renewal_reminder",
        ): "MANA: срок доступа заканчивается. Проверьте условия в приложении.",
        (
            "uz",
            "onboarding_help",
        ): "MANA: sozlashda yordam kerakmi? Ilovadagi yordam bo‘limini oching.",
        (
            "uz",
            "renewal_reminder",
        ): "MANA: foydalanish muddati tugamoqda. Ilovadagi shartlarni tekshiring.",
    }
)


def contact_message(parameters: RetentionContactParameters) -> RetentionContactMessage:
    text = _TEXTS[parameters.language, parameters.template]
    return RetentionContactMessage(
        template=parameters.template,
        language=parameters.language,
        version="retention-contact-uz-v1"
        if parameters.language == "uz"
        else "retention-contact-ru-v1",
        text=text,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
    )


def contact_dispatch_fingerprint(
    parameters: RetentionContactParameters,
    message: RetentionContactMessage,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "parameters": parameters.model_dump(mode="json"),
                "message": message.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
