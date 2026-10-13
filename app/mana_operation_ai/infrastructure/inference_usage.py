"""Raw response usage is independent of structured-answer validation."""

from pydantic import BaseModel, Field

from app.mana_operation_ai.application.inference_errors import InferencePendingStatus


def pending_usage_status(payload: object) -> InferencePendingStatus | None:
    """An explicitly running request cannot supply its final billable usage yet."""
    if not isinstance(payload, dict) or type(payload.get("status")) is not str:
        return None
    if payload["status"] == "queued":
        return "queued"
    if payload["status"] == "in_progress":
        return "in_progress"
    return None


class InferenceInputUsage(BaseModel):
    cached_tokens: int = Field(ge=0, strict=True)
    cache_write_tokens: int = Field(default=0, ge=0, strict=True)


class InferenceUsage(BaseModel):
    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)
    input_tokens_details: InferenceInputUsage


class InferenceUsageEnvelope(BaseModel):
    """Only pricing facts: malformed answer/error metadata must not hide valid usage."""

    model: str
    service_tier: str | None
    usage: InferenceUsage | None
