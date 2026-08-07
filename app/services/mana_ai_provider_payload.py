from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.mana_ai.domain.requests import ManaAIRequest
from app.mana_ai.domain.responses import CheckResult, FindingDraft

PRIVATE_LOCATION_FIELDS = frozenset({"latitude", "longitude"})


def build_provider_payload(
    request: ManaAIRequest,
    *,
    deterministic_findings: list[FindingDraft],
    required_checks: list[CheckResult],
) -> dict[str, Any]:
    return {
        "capability": request.input.capability.value,
        "occurred_at": request.occurred_at.isoformat(),
        "locale": request.locale,
        "subject": {
            "age_band": request.subject.age_band.value,
            "timezone": request.subject.timezone,
            "policy_version": request.subject.policy_version,
        },
        "capability_input": _sanitize(request.input.model_dump(mode="json")),
        "deterministic_findings": _sanitize(
            [item.model_dump(mode="json") for item in deterministic_findings]
        ),
        "required_checks": _sanitize([item.model_dump(mode="json") for item in required_checks]),
    }


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in PRIVATE_LOCATION_FIELDS:
                continue
            if key == "normalized_value" and isinstance(item, str):
                result[key] = _strip_url_secrets(item)
            else:
                result[key] = _sanitize(item)
        return result
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _strip_url_secrets(value: str) -> str:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return "[redacted-invalid-url]"
    if parsed.scheme not in {"http", "https"} or not hostname:
        return value
    if ":" in hostname:
        hostname = f"[{hostname}]"
    if port is not None:
        hostname = f"{hostname}:{port}"
    return urlunsplit((parsed.scheme, hostname, parsed.path, "", ""))
