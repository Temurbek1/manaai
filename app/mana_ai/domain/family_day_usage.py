"""A requested calendar label is not a verified screen-time measurement period."""

from datetime import date, datetime

from pydantic import AwareDatetime, Field, SecretStr, field_validator, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId
from app.mana_ai.domain.family_sources import ChildAppUsageFacts


class ParentUsageLookup(ChatContract):
    """Ephemeral server lookup; the username is never serialized or model-visible."""

    parent_id: ParentChatId
    username: SecretStr = Field(exclude=True, repr=False)
    connected_child_ids: tuple[int, ...] = Field(max_length=20)
    collected_at: AwareDatetime

    @field_validator("username")
    @classmethod
    def bounded_username(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not 1 <= len(raw) <= 80 or any(ord(c) < 32 or ord(c) == 127 for c in raw):
            raise ValueError("A bounded server-only account lookup is required")
        return value

    @model_validator(mode="after")
    def canonical_scope(self) -> "ParentUsageLookup":
        if (
            int(self.parent_id) > 2**63 - 1
            or len(set(self.connected_child_ids)) != len(self.connected_child_ids)
            or any(type(c) is not int or not 0 < c <= 2**63 - 1 for c in self.connected_child_ids)
        ):
            raise ValueError("Invalid canonical family lookup")
        return self


class FamilyDayUsagePage(ChatContract):
    parent_id: ParentChatId
    requested_day: date
    ownership_collected_at: AwareDatetime
    collected_at: AwareDatetime
    owned_children_count: int = Field(ge=0, le=20, strict=True)
    provider_children_count: int = Field(ge=0, le=20, strict=True)
    children: tuple[ChildAppUsageFacts, ...] = Field(max_length=10)
    complete_family: bool = Field(strict=True)
    provider_timezone: None = None
    verified_measurement_period: None = None

    @model_validator(mode="after")
    def coherent_page(self) -> "FamilyDayUsagePage":
        if (
            int(self.parent_id) > 2**63 - 1
            or len({c.child_id for c in self.children}) != len(self.children)
            or len(self.children) > self.provider_children_count
            or self.provider_children_count > self.owned_children_count
            or self.complete_family
            != (len(self.children) == self.provider_children_count == self.owned_children_count)
            or not 0 <= (self.collected_at - self.ownership_collected_at).total_seconds() <= 180
            or any(c.collected_at != self.collected_at for c in self.children)
            or any(
                datetime.strptime(e.provider_recorded_at, "%Y-%m-%d %H:%M:%S").date()
                != self.requested_day
                for c in self.children
                for e in c.entries
            )
        ):
            raise ValueError("Invalid own-family day-page coverage or dates")
        return self
