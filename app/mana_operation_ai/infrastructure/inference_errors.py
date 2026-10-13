"""Classify allowlisted SDK facts, never serialize exceptions or provider bodies."""

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

from app.mana_operation_ai.application.inference_errors import (
    InferenceFailureKind,
    InferenceProviderError,
)

QUOTA_CODES = {
    "insufficient_quota",
    "credit_balance_exhausted",
    "project_spend_limit_exceeded",
    "organization_spend_limit_exceeded",
    "organization_usage_limit_exceeded",
}


def response_failure(code: object) -> InferenceProviderError:
    kind: InferenceFailureKind = "invalid_response"
    if isinstance(code, str):
        if code in QUOTA_CODES:
            kind = "quota"
        elif code in {"rate_limit_exceeded", "slow_down"}:
            kind = "rate_limit"
        elif code in {"server_error", "server_is_overloaded", "server_overloaded"}:
            kind = "unavailable"
        elif code in {"invalid_api_key", "authentication_error"}:
            kind = "authentication"
    return InferenceProviderError(kind)


def sdk_failure(exc: APIConnectionError | APIStatusError) -> InferenceProviderError:
    status = exc.status_code if isinstance(exc, APIStatusError) else None
    kind: InferenceFailureKind
    if isinstance(exc, APITimeoutError):
        kind = "timeout"
    elif isinstance(exc, APIConnectionError):
        kind = "connection"
    elif isinstance(exc, AuthenticationError):
        kind = "authentication"
    elif isinstance(exc, PermissionDeniedError):
        kind = "permission"
    elif isinstance(exc, RateLimitError):
        kind = "quota" if isinstance(exc.code, str) and exc.code in QUOTA_CODES else "rate_limit"
    elif isinstance(exc, InternalServerError):
        kind = "unavailable"
    elif isinstance(exc, BadRequestError | NotFoundError):
        kind = "invalid_request"
    else:
        kind = "unavailable" if status and status >= 500 else "invalid_request"
    return InferenceProviderError(kind, http_status=status)
