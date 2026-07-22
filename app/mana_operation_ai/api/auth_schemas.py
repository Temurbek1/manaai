from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.mana_operation_ai.domain.enums import AdminUserStatus, AuthAuditEventType, UserRole


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class TelegramIdentityRequest(ApiModel):
    telegram_id: int = Field(gt=0, le=9_007_199_254_740_991)


class TelegramCodeRequest(TelegramIdentityRequest):
    code: str = Field(pattern=r"^\d{6}$")


class RequestCodeResponse(ApiModel):
    message: str
    expires_in_seconds: Literal[60]
    resend_after_seconds: int
    bot_url: str | None


class AdminUserResponse(ApiModel):
    user_id: str
    telegram_id: int
    display_name: str | None
    username: str | None
    role: UserRole
    status: AdminUserStatus
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None
    created_by: str
    disabled_reason: str | None
    profile_metadata: dict[str, object]
    auth_locked_until: datetime | None


class SessionUserResponse(ApiModel):
    user_id: str
    telegram_id: int
    display_name: str | None
    username: str | None
    role: UserRole
    permissions: list[str]


class AuthSessionResponse(ApiModel):
    authenticated: bool
    user: SessionUserResponse | None = None
    expires_at: datetime | None = None
    ads_provider: str | None = None
    provider_mode: str | None = None
    live_meta_read_only: bool = False


class UserPage(ApiModel):
    items: list[AdminUserResponse]
    total: int


class CreateAdminUserRequest(TelegramIdentityRequest):
    role: UserRole
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    username: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.removeprefix("@").strip()
        if not normalized:
            raise ValueError("username cannot be empty")
        return normalized


class UpdateAdminUserRequest(ApiModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    username: str | None = Field(default=None, min_length=1, max_length=64)
    role: UserRole | None = None
    status: Literal[AdminUserStatus.ACTIVE, AdminUserStatus.DISABLED] | None = None
    disabled_reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_change(self) -> "UpdateAdminUserRequest":
        if not self.model_fields_set.intersection({"display_name", "username", "role", "status"}):
            raise ValueError("at least one user field is required")
        if self.status is AdminUserStatus.DISABLED and self.disabled_reason is None:
            raise ValueError("disabled_reason is required when disabling a user")
        if self.status is AdminUserStatus.ACTIVE and self.disabled_reason is not None:
            raise ValueError("disabled_reason is forbidden when enabling a user")
        return self

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.removeprefix("@").strip()
        if not normalized:
            raise ValueError("username cannot be empty")
        return normalized


class SessionRevocationResponse(ApiModel):
    revoked_sessions: int = Field(ge=0)


class AuthAuditEventResponse(ApiModel):
    event_id: str
    event_type: AuthAuditEventType
    occurred_at: datetime
    actor_user_id: str | None
    subject_user_id: str | None
    summary: str
    details: dict[str, object]


class AuthAuditPage(ApiModel):
    items: list[AuthAuditEventResponse]
    total: int
