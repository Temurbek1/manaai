"""Private native source-call pairing, never public tool or ownership authority."""

import hashlib
import json
from typing import Literal
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId


def source_arguments(value: str) -> str:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("Duplicate source argument")
            result[key] = item
        return result

    payload = json.loads(value, object_pairs_hook=unique)
    return BatterySourceArguments.model_validate(payload).child_alias


class BatterySourceArguments(ChatContract):
    child_alias: str = Field(pattern=r"^child-[1-9][0-9]?$", strict=True)


class SourceToolChild(ChatContract):
    alias: str = Field(pattern=r"^child-[1-9][0-9]?$", strict=True)
    child_id: int = Field(gt=0, le=2**63 - 1, strict=True)


class SourceToolScope(ChatContract):
    parent_id: ParentChatId
    invocation_id: UUID
    children: tuple[SourceToolChild, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_children(self) -> "SourceToolScope":
        if int(self.parent_id) > 2**63 - 1 or (
            len({child.alias for child in self.children}) != len(self.children)
            or len({child.child_id for child in self.children}) != len(self.children)
        ):
            raise ValueError("Invalid native source family scope")
        return self

    def request_id_for(self, call: "BatterySourceCall") -> UUID:
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


class EncryptedSourceReasoning(ChatContract):
    type: Literal["reasoning"] = "reasoning"
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$", strict=True)
    encrypted_content: str = Field(min_length=1, max_length=32768, strict=True)


class SourceToolContinuation(ChatContract):
    version: Literal[1] = 1
    input_digest: str = Field(pattern=r"^[a-f0-9]{64}$", strict=True)
    items: tuple[BatterySourceCall | EncryptedSourceReasoning, ...] = Field(
        min_length=1, max_length=5
    )

    @model_validator(mode="after")
    def one_call(self) -> "SourceToolContinuation":
        if (
            sum(isinstance(item, BatterySourceCall) for item in self.items) != 1
            or len({item.id for item in self.items}) != len(self.items)
            or len(self.model_dump_json().encode()) > 65536
        ):
            raise ValueError("A bounded original native source call is required")
        return self

    @property
    def call(self) -> BatterySourceCall:
        return next(item for item in self.items if isinstance(item, BatterySourceCall))
