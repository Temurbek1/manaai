"""Raw response usage is independent of structured-answer validation."""

from pydantic import BaseModel, Field


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
