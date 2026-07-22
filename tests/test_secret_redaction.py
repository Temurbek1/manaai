import json
import logging

from app.core.logging import (
    SecretRedactor,
    StructuredJsonFormatter,
    configure_application_logging,
)


def test_structured_logging_redacts_known_and_named_secrets() -> None:
    formatter = StructuredJsonFormatter(SecretRedactor(["known-secret-value"]))
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="request access_token=known-secret-value",
        args=(),
        exc_info=None,
    )
    record.context = {
        "authorization": "Bearer known-secret-value",
        "url": "https://example.test/?api_key=another-secret",
    }

    payload = json.loads(formatter.format(record))
    serialized = json.dumps(payload)
    assert "known-secret-value" not in serialized
    assert "another-secret" not in serialized
    assert serialized.count("[REDACTED]") >= 2


def test_structured_logging_redacts_telegram_tokens_and_otp_assignments() -> None:
    formatter = StructuredJsonFormatter(
        SecretRedactor(["test-bot-token-sensitive", "test-hmac-secret-sensitive"]),
    )
    record = logging.LogRecord(
        name="app.auth",
        level=logging.ERROR,
        pathname=__file__,
        lineno=20,
        msg=(
            "bot_token=test-bot-token-sensitive hmac_secret=test-hmac-secret-sensitive otp=123456"
        ),
        args=(),
        exc_info=None,
    )
    serialized = formatter.format(record)
    assert "test-bot-token-sensitive" not in serialized
    assert "test-hmac-secret-sensitive" not in serialized
    assert "123456" not in serialized


def test_http_client_request_logging_is_suppressed_to_protect_url_tokens() -> None:
    configure_application_logging(level="INFO", secrets=[])
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
