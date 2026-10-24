"""Private native source-call pairing, never public tool or ownership authority."""

import hashlib
import json
from typing import Literal
from uuid import UUID, uuid5

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId
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


class SourceToolChild(ChatContract):
    alias: str = Field(pattern=r"^child-[1-9][0-9]?$", strict=True)
    child_id: int = Field(gt=0, le=2**63 - 1, strict=True)


class SourceToolScope(ChatContract):
    parent_id: ParentChatId
    invocation_id: UUID
    children: tuple[SourceToolChild, ...] = Field(max_length=20)
    protocol: Literal[1, 2] = 1

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
        return self

    def request_id_for(self, call: "BatterySourceCall | ObservationSourceCall") -> UUID:
        identity = hashlib.sha256(call.model_dump_json().encode()).hexdigest()
        return uuid5(self.invocation_id, "native-source-read-v1:" + identity)


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


def source_call_alias(call: BatterySourceCall | ObservationSourceCall) -> str:
    return (
        source_arguments(call.arguments)
        if isinstance(call, BatterySourceCall)
        else observation_arguments(call.arguments).child_alias
    )


def source_call_key(call: BatterySourceCall | ObservationSourceCall) -> FamilySourceKey:
    return (
        "firebase.child_battery.v1"
        if isinstance(call, BatterySourceCall)
        or observation_arguments(call.arguments).kind == "battery"
        else "manakids.child_app_usage.v1"
    )


class EncryptedSourceReasoning(ChatContract):
    type: Literal["reasoning"] = "reasoning"
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$", strict=True)
    encrypted_content: str = Field(min_length=1, max_length=32768, strict=True)


class SourceToolContinuation(ChatContract):
    version: Literal[1, 2] = 1
    input_digest: str = Field(pattern=r"^[a-f0-9]{64}$", strict=True)
    items: tuple[BatterySourceCall | ObservationSourceCall | EncryptedSourceReasoning, ...] = Field(
        min_length=1, max_length=5
    )

    @model_validator(mode="after")
    def one_call(self) -> "SourceToolContinuation":
        if (
            sum(isinstance(item, BatterySourceCall | ObservationSourceCall) for item in self.items)
            != 1
            or any(
                isinstance(item, ObservationSourceCall) != (self.version == 2)
                for item in self.items
                if isinstance(item, BatterySourceCall | ObservationSourceCall)
            )
            or len({item.id for item in self.items}) != len(self.items)
            or len(self.model_dump_json().encode()) > 65536
        ):
            raise ValueError("A bounded original native source call is required")
        return self

    @property
    def call(self) -> BatterySourceCall | ObservationSourceCall:
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
