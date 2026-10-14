"""Model-selected fictional parameters, never a read/write/consent grant."""

import hashlib
import json
from typing import Final, Literal

from pydantic import Field

from app.mana_operation_ai.domain.models import DomainModel
from app.mana_operation_ai.domain.retention_contact import ContactTemplate, SandboxRecipient

CONTACT_TOOL: Final = "request_retention_contact_preparation"
CONTACT_TOOL_CONTRACT: Final = "native_contact_preparation_v1"


class ContactToolSelection(DomainModel):
    recipient: SandboxRecipient
    template: ContactTemplate


class ContactToolRequest(ContactToolSelection):
    contract: Literal["native_contact_preparation_v1"] = CONTACT_TOOL_CONTRACT
    tool_name: Literal["request_retention_contact_preparation"] = CONTACT_TOOL
    provider_call_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    selection_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmation_required: Literal[True] = True
    synthetic: Literal[True] = True


def contact_selection_fingerprint(
    owner: str, topic_id: str, turn_id: str, selection: ContactToolSelection, call_sha256: str
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "contract": CONTACT_TOOL_CONTRACT,
                "owner": owner,
                "topic_id": topic_id,
                "turn_id": turn_id,
                "parameters": {"recipient": selection.recipient, "template": selection.template},
                "provider_call_sha256": call_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
