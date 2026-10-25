"""The single, application-facing parent chat; unrelated to operational topics."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

ParentChatId = Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{0,18}$", strict=True)]
ResponseLanguage = Literal["ru", "uz-Latn", "uz-Cyrl", "en"]
TurnStatus = Literal["preparing", "submitted", "completed", "failed", "unknown"]


class ChatContract(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, frozen=True)


class ChatAppUsage(ChatContract):
    app_name: str = Field(min_length=1, max_length=80)
    minutes: int = Field(ge=0, le=44_640, strict=True)


class ChildChatObservation(ChatContract):
    """Minimized facts supplied by the authenticated application backend."""

    child_id: int = Field(gt=0, strict=True)
    observed_at: AwareDatetime
    battery_percent: int | None = Field(default=None, ge=0, le=100, strict=True)
    location_label: str | None = Field(default=None, min_length=1, max_length=100)
    screen_time_minutes: int | None = Field(default=None, ge=0, le=44_640, strict=True)
    apps: list[ChatAppUsage] = Field(default_factory=list, max_length=5)
    activity_period_start: AwareDatetime | None = None
    activity_period_end: AwareDatetime | None = None

    @model_validator(mode="after")
    def check_observation_period(self) -> "ChildChatObservation":
        has_usage = self.screen_time_minutes is not None or bool(self.apps)
        has_period = self.activity_period_start is not None or self.activity_period_end is not None
        if has_usage or has_period:
            start, end = self.activity_period_start, self.activity_period_end
            if start is None or end is None or not start < end <= self.observed_at:
                raise ValueError("Usage requires an explicit, completed observation period")
            if (end - start).total_seconds() > 31 * 86_400:
                raise ValueError("The activity period cannot exceed 31 days")
            available = (end - start).total_seconds() / 60
            if self.screen_time_minutes is not None and self.screen_time_minutes > available:
                raise ValueError("Screen time exceeds the observation period")
            if any(app.minutes > available for app in self.apps):
                raise ValueError("App usage exceeds the observation period")
        return self


class ParentChatRequest(ChatContract):
    parent_id: ParentChatId
    request_id: UUID
    message: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    child_observations: list[ChildChatObservation] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def check_unique_children(self) -> "ParentChatRequest":
        identifiers = [item.child_id for item in self.child_observations]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Child observations must not contain duplicate children")
        return self


class ChatTokens(ChatContract):
    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


class ChatQuota(ChatContract):
    daily_limit: int
    used_tokens: int
    reserved_tokens: int
    remaining_tokens: int
    resets_at: AwareDatetime
    timezone: str
    blocked_by_unresolved_request: bool = False


class ParentChatMessage(ChatContract):
    turn_id: int
    request_id: UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: AwareDatetime
    status: TurnStatus


class ParentChatResponse(ChatContract):
    parent_id: ParentChatId
    request_id: UUID
    answer: str
    model: str
    usage: ChatTokens
    quota: ChatQuota
    history_turns_included: int
    child_context_collected_at: AwareDatetime | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class ParentChatHistory(ChatContract):
    parent_id: ParentChatId
    messages: list[ParentChatMessage]
    next_before_turn_id: int | None
    quota: ChatQuota
    latest_request_id: UUID | None = None
    latest_request_status: TurnStatus | None = None
    latest_error_code: str | None = None


class ChatChild(ChatContract):
    """Allowlisted facts, never raw provider records, phone numbers or media URLs."""

    child_id: int = Field(gt=0, strict=True)
    name: str | None = Field(default=None, max_length=100)
    age: int | None = Field(default=None, ge=1, le=17, strict=True)
    connected: bool = Field(strict=True)


class ParentChildContext(ChatContract):
    parent_id: ParentChatId
    children: list[ChatChild] = Field(max_length=20)
    collected_at: AwareDatetime
    limitations: list[str] = Field(max_length=5)


class StoredChatTurn(ChatContract):
    turn_id: int
    request_id: UUID
    parent_id: ParentChatId
    message: str
    status: TurnStatus
    reserved_tokens: int
    created_at: datetime
    answer: str | None = None
    result: ParentChatResponse | None = None
    error_code: str | None = None
