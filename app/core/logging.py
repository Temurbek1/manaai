import json
import logging
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

SECRET_ASSIGNMENT = re.compile(
    r"(?i)(access_token|api_key|authorization|client_secret)(\s*[=:]\s*)([^\s,&]+)",
)
STANDARD_LOG_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__)


class SecretRedactor:
    def __init__(self, secrets: Iterable[str]) -> None:
        self._secrets = tuple(secret for secret in secrets if secret)

    def sanitize(self, value: object) -> object:
        if isinstance(value, str):
            sanitized = value
            for secret in self._secrets:
                sanitized = sanitized.replace(secret, "[REDACTED]")
            return SECRET_ASSIGNMENT.sub(r"\1\2[REDACTED]", sanitized)
        if isinstance(value, Mapping):
            return {str(key): self.sanitize(item) for key, item in value.items()}
        if isinstance(value, list | tuple | set | frozenset):
            return [self.sanitize(item) for item in value]
        return value


class StructuredJsonFormatter(logging.Formatter):
    def __init__(self, redactor: SecretRedactor) -> None:
        super().__init__()
        self._redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self._redactor.sanitize(record.getMessage()),
        }
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in STANDARD_LOG_RECORD_FIELDS and key not in {"message", "asctime"}
        }
        if extras:
            payload["context"] = self._redactor.sanitize(extras)
        if record.exc_info:
            payload["exception"] = self._redactor.sanitize(
                self.formatException(record.exc_info),
            )
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_application_logging(*, level: str, secrets: Iterable[str]) -> None:
    application_logger = logging.getLogger("app")
    application_logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredJsonFormatter(SecretRedactor(secrets)))
    application_logger.addHandler(handler)
    application_logger.setLevel(level.upper())
    application_logger.propagate = False
