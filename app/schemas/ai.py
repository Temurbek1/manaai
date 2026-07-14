from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=8_000)
    system_prompt: str | None = Field(
        default=None,
        min_length=1,
        max_length=2_000,
        description="Optional system instruction for the model.",
    )


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    model: str


class SummarizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=20_000)
    max_sentences: int = Field(default=3, ge=1, le=10)


class SummarizeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    model: str
