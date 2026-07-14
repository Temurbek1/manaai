from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    dependencies: dict[str, str]
