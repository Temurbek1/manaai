import json
import logging

from app.core.logging import SecretRedactor, StructuredJsonFormatter


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
