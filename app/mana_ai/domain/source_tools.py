"""Private native source-call pairing, never public tool or ownership authority."""

import hashlib
import json
from datetime import date
from typing import Literal
from uuid import UUID, uuid5

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId
from app.mana_ai.domain.family_day_usage import DAY_USAGE_SOURCE
from app.mana_ai.domain.family_sources import FamilySourceKey


def _source_payload(value: str) -> object:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("Duplicate source argument")
            result[key] = item
        return result

    return json.loads(value, object_pairs_hook=unique)


def source_arguments(value: str) -> str:
    return BatterySourceArguments.model_validate(_source_payload(value)).child_alias


class BatterySourceArguments(ChatContract):
    child_alias: str = Field(pattern=r"^child-[1-9][0-9]?$", strict=True)


class ObservationSourceArguments(BatterySourceArguments):
    kind: Literal["battery", "app_usage"]


class DatedObservationArguments(BatterySourceArguments):
    kind: Literal["battery", "app_usage", "app_usage_day", "location"]
    calendar_day: str | None = Field(pattern=r"^\d{4}-\d{2}-\d{2}$", strict=True)

    @model_validator(mode="after")
    def exact_day(self) -> "DatedObservationArguments":
        if (self.kind == "app_usage_day") != (self.calendar_day is not None):
            raise ValueError("Only a dated usage read takes a calendar day")
        if self.calendar_day is not None:
            date.fromisoformat(self.calendar_day)
        return self


class SourceToolChild(ChatContract):
    alias: str = Field(pattern=r"^child-[1-9][0-9]?$", strict=True)
    child_id: int = Field(gt=0, le=2**63 - 1, strict=True)


class SourceToolScope(ChatContract):
    parent_id: ParentChatId
    invocation_id: UUID
    children: tuple[SourceToolChild, ...] = Field(max_length=20)
    protocol: Literal[1, 2, 3, 4, 5] = 1
    calendar_today: date | None = Field(default=None, exclude_if=lambda v: v is None)
    location_enabled: Literal[True] | None = Field(default=None, exclude_if=lambda v: v is None)
    location_prompt_version: Literal[2] | None = Field(default=None, exclude_if=lambda v: v is None)
    input_presentation: Literal[1] | None = Field(default=None, exclude_if=lambda v: v is None)
    saved_observations_enabled: Literal[True] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )

    request_projection_hash: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$", exclude_if=lambda v: v is None
    )

    @model_serializer(mode="wrap")
    def original_scope(self, handler: SerializerFunctionWrapHandler) -> object:
        result = handler(self)
        if self.protocol == 1 and isinstance(result, dict):
            result.pop("protocol", None)
        return result

    @model_validator(mode="after")
    def unique_children(self) -> "SourceToolScope":
        if int(self.parent_id) > 2**63 - 1 or (
            len({child.alias for child in self.children}) != len(self.children)
            or len({child.child_id for child in self.children}) != len(self.children)
        ):
            raise ValueError("Invalid native source family scope")
        if (self.protocol in {3, 4, 5}) != (self.calendar_today is not None):
            raise ValueError("Only dated source scopes freeze their query-calendar date")
        if self.location_enabled is not None and self.protocol not in {3, 4, 5}:
            raise ValueError("Location tools require the new captured dated-source profile")
        if self.location_prompt_version is not None and self.location_enabled is not True:
            raise ValueError("A location prompt version requires its original source capture")
        if (self.protocol in {4, 5}) != (self.saved_observations_enabled is True):
            raise ValueError("Saved SQL inspection requires its new captured source protocol")
        if (self.protocol == 5) != (self.request_projection_hash is not None):
            raise ValueError("Compact source requests require their exact new frame capture")
        return self

    def validate_call(
        self, call: "BatterySourceCall | ObservationSourceCall | DatedObservationCall"
    ) -> None:
        expected = {
            1: BatterySourceCall,
            2: ObservationSourceCall,
            3: DatedObservationCall,
            4: DatedObservationCall,
            5: UnifiedObservationCall,
        }[self.protocol]
        if isinstance(call, UnifiedObservationCall) and self.protocol != 5:
            raise ValueError("Unified source access was not captured in this scope")
        if not isinstance(call, expected) or source_call_alias(call) not in {
            c.alias for c in self.children
        }:
            raise ValueError("The exact captured source protocol and child are required")
        if isinstance(call, SavedObservationCall) and self.saved_observations_enabled is not True:
            raise ValueError("Saved inspection was not captured in this source scope")
        day = source_call_day(call)
        if source_call_key(call) == "firebase.child_location.v1" and not self.location_enabled:
            raise ValueError("Location was not captured in this source scope")
        if day is not None and (
            self.calendar_today is None or not 1 <= (self.calendar_today - day).days <= 31
        ):
            raise ValueError("The query day is outside the captured completed-day window")

    def request_id_for(
        self, call: "BatterySourceCall | ObservationSourceCall | DatedObservationCall"
    ) -> UUID:
        identity = hashlib.sha256(call.model_dump_json().encode()).hexdigest()
        return uuid5(
            self.invocation_id,
            (
                "native-saved-inspection-v1:"
                if source_call_access(call) == "saved_only"
                else "native-source-read-v1:"
            )
            + identity,
        )


class BatterySourceCall(ChatContract):
    type: Literal["function_call"] = "function_call"
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$", strict=True)
    call_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$", strict=True)
    name: Literal["read_child_battery"] = "read_child_battery"
    arguments: str = Field(min_length=1, max_length=1024, strict=True)

    @model_validator(mode="after")
    def valid_arguments(self) -> "BatterySourceCall":
        source_arguments(self.arguments)
        return self


def observation_arguments(value: str) -> ObservationSourceArguments:
    return ObservationSourceArguments.model_validate(_source_payload(value))


class ObservationSourceCall(ChatContract):
    type: Literal["function_call"] = "function_call"
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$", strict=True)
    call_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$", strict=True)
    name: Literal["read_child_observation"] = "read_child_observation"
    arguments: str = Field(min_length=1, max_length=1024, strict=True)

    @model_validator(mode="after")
    def valid_arguments(self) -> "ObservationSourceCall":
        observation_arguments(self.arguments)
        return self


class DatedObservationCall(ObservationSourceCall):
    @model_validator(mode="after")
    def valid_arguments(self) -> "DatedObservationCall":
        dated_arguments(self.arguments)
        return self


class SavedObservationCall(DatedObservationCall):
    name: Literal["inspect_saved_child_observation"] = "inspect_saved_child_observation"  # type: ignore[assignment]


class UnifiedObservationArguments(DatedObservationArguments):
    access: Literal["saved_only", "live"]


def unified_arguments(value: str) -> UnifiedObservationArguments:
    return UnifiedObservationArguments.model_validate(_source_payload(value))


class UnifiedObservationCall(DatedObservationCall):
    @model_validator(mode="after")
    def valid_arguments(self) -> "UnifiedObservationCall":
        unified_arguments(self.arguments)
        return self


def source_call_access(
    call: BatterySourceCall | ObservationSourceCall,
) -> Literal["saved_only", "live"]:
    if isinstance(call, UnifiedObservationCall):
        return unified_arguments(call.arguments).access
    return "saved_only" if isinstance(call, SavedObservationCall) else "live"


def dated_arguments(value: str) -> DatedObservationArguments:
    return DatedObservationArguments.model_validate(_source_payload(value))


def source_call_alias(
    call: BatterySourceCall | ObservationSourceCall | DatedObservationCall,
) -> str:
    if isinstance(call, UnifiedObservationCall):
        return unified_arguments(call.arguments).child_alias
    if isinstance(call, DatedObservationCall):
        return dated_arguments(call.arguments).child_alias
    return (
        source_arguments(call.arguments)
        if isinstance(call, BatterySourceCall)
        else observation_arguments(call.arguments).child_alias
    )


def source_call_key(
    call: BatterySourceCall | ObservationSourceCall | DatedObservationCall,
) -> FamilySourceKey | Literal["manakids.family_day_app_usage.v1"]:
    if isinstance(call, DatedObservationCall):
        kind = (
            unified_arguments(call.arguments)
            if isinstance(call, UnifiedObservationCall)
            else dated_arguments(call.arguments)
        ).kind
        return (
            DAY_USAGE_SOURCE
            if kind == "app_usage_day"
            else "firebase.child_location.v1"
            if kind == "location"
            else "firebase.child_battery.v1"
            if kind == "battery"
            else "manakids.child_app_usage.v1"
        )
    return (
        "firebase.child_battery.v1"
        if isinstance(call, BatterySourceCall)
        or observation_arguments(call.arguments).kind == "battery"
        else "manakids.child_app_usage.v1"
    )


def source_call_day(
    call: BatterySourceCall | ObservationSourceCall | DatedObservationCall,
) -> date | None:
    value = (
        (
            unified_arguments(call.arguments)
            if isinstance(call, UnifiedObservationCall)
            else dated_arguments(call.arguments)
        ).calendar_day
        if isinstance(call, DatedObservationCall)
        else None
    )
    return date.fromisoformat(value) if value is not None else None


class EncryptedSourceReasoning(ChatContract):
    type: Literal["reasoning"] = "reasoning"
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$", strict=True)
    encrypted_content: str = Field(min_length=1, max_length=32768, strict=True)


class SourceToolContinuation(ChatContract):
    version: Literal[1, 2, 3, 4, 5] = 1
    input_digest: str = Field(pattern=r"^[a-f0-9]{64}$", strict=True)
    items: tuple[
        BatterySourceCall
        | UnifiedObservationCall
        | SavedObservationCall
        | DatedObservationCall
        | ObservationSourceCall
        | EncryptedSourceReasoning,
        ...,
    ] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def one_call(self) -> "SourceToolContinuation":
        if (
            sum(isinstance(item, BatterySourceCall | ObservationSourceCall) for item in self.items)
            != 1
            or any(
                type(item)
                not in {
                    1: (BatterySourceCall,),
                    2: (ObservationSourceCall,),
                    3: (DatedObservationCall,),
                    4: (DatedObservationCall, SavedObservationCall),
                    5: (UnifiedObservationCall,),
                }[self.version]
                for item in self.items
                if isinstance(item, BatterySourceCall | ObservationSourceCall)
            )
            or len({item.id for item in self.items}) != len(self.items)
            or len(self.model_dump_json().encode()) > 65536
        ):
            raise ValueError("A bounded original native source call is required")
        return self

    @property
    def call(self) -> BatterySourceCall | ObservationSourceCall | DatedObservationCall:
        return next(
            item
            for item in self.items
            if isinstance(item, BatterySourceCall | ObservationSourceCall)
        )


class SourceToolPreparedInput(ChatContract):
    version: Literal[1] = 1
    scope: SourceToolScope
    input_digest: str = Field(pattern=r"^[a-f0-9]{64}$", strict=True)
    instructions: str = Field(min_length=1, max_length=65536, strict=True)
    messages: tuple[tuple[Literal["user", "assistant"], str], ...] = Field(
        min_length=1, max_length=20
    )
    minimum_output_tokens: int = Field(default=32, ge=32, le=4096, strict=True)

    @model_validator(mode="after")
    def bounded_input(self) -> "SourceToolPreparedInput":
        if len(self.model_dump_json().encode()) > 65536:
            raise ValueError("Native source input exceeds its private bound")
        return self


class SourceToolModelProfile(ChatContract):
    version: Literal[1] = 1
    model_name: str = Field(min_length=1, max_length=128, strict=True)
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"]
    verbosity: Literal["low", "medium", "high"]
    wall_timeout_seconds: float = Field(ge=10, le=130)
