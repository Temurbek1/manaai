"""Private exact tool pairing and frozen SQL preparation result; never a send grant."""

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.mana_operation_ai.domain.contact_preparation import ContactToolRequest
from app.mana_operation_ai.domain.models import DomainModel
from app.mana_operation_ai.domain.retention_contact import (
    ContactStatus,
    ContactTemplate,
    RetentionContactMessage,
)


class ContactModelWindow(DomainModel):
    model: str = Field(min_length=1, max_length=100)
    effort: Literal["none", "low", "medium", "high", "xhigh"]
    instructions: str = Field(min_length=1, max_length=32000)
    context: str = Field(min_length=1, max_length=200000)
    items: str = Field(min_length=1, max_length=262144)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def integrity(self) -> "ContactModelWindow":
        if self.digest != window_digest(
            self.model, self.effort, self.instructions, self.context, self.items
        ):
            raise ValueError("Contact model window integrity mismatch")
        return self


def window_digest(model: str, effort: str, instructions: str, context: str, items: str) -> str:
    return hashlib.sha256(
        json.dumps([model, effort, instructions, context, items], ensure_ascii=False).encode()
    ).hexdigest()


class BoundContactWindow(DomainModel):
    protocol: Literal["contact-model-continuation-v1", "contact-model-continuation-v2"] = (
        "contact-model-continuation-v1"
    )
    selection_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    window: ContactModelWindow


def verify_window_request(
    window: ContactModelWindow,
    request: ContactToolRequest,
    *,
    topic_id: str,
    message: str,
    response_language: str | None,
) -> None:
    context = json.loads(window.context)
    calls = [item for item in json.loads(window.items) if item.get("type") == "function_call"]
    if (
        context.get("topic", {}).get("topic_id") != topic_id
        or context.get("topic", {}).get("product") != "mana"
        or context.get("topic", {}).get("agent_id")
        not in {"retention-agent", "operations-orchestrator"}
        or context.get("message") != message
        or context.get("response_language") != response_language
        or context.get("contact_tool_contract") != request.contract
        or request.contract != "native_contact_preparation_v2"
        or len(calls) != 1
        or calls[0].get("name") != request.tool_name
        or hashlib.sha256(str(calls[0].get("call_id")).encode()).hexdigest()
        != request.provider_call_sha256
        or json.loads(str(calls[0].get("arguments")))
        != {"recipient": request.recipient, "template": request.template}
    ):
        raise ValueError("Original contact continuation facts do not match the admitted turn")


class ContactPreparationResult(DomainModel):
    """A dated SQL observation, never a real delivery or a grant for another action."""

    origin_turn_id: str = Field(min_length=1, max_length=100)
    selection_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    action_id: str = Field(min_length=1, max_length=100)
    action_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: int = Field(ge=0, strict=True)
    observed_at: AwareDatetime
    template: ContactTemplate
    message: RetentionContactMessage
    status: ContactStatus
    result_code: str = Field(min_length=1, max_length=100)
    approval_is_separate: Literal[True] = True
    synthetic: Literal[True] = True
    delivered: Literal[False] = False
    business_outcome: Literal["not_measured"] = "not_measured"


class ContactResultMeaning(DomainModel):
    """Host-owned lifecycle vocabulary, not additional execution authority."""

    preparation_recorded: Literal[True] = True
    preparation_is_approval: Literal[False] = False
    next_human_step: Literal["separate_human_approval", "observe_without_redispatch", "none"]
    status_explanation: str = Field(min_length=1, max_length=500)


def contact_result_meaning(status: ContactStatus) -> ContactResultMeaning:
    if status == "proposed":
        return ContactResultMeaning(
            next_human_step="separate_human_approval",
            status_explanation=(
                "The human-confirmed preparation already created a saved action and exact "
                "message. Do not ask for preparation again. A different authorized human "
                "must separately review/approve this prepared action before any fake send; "
                "this observation grants no approval or current eligibility."
            ),
        )
    if status in {"dispatching", "uncertain"}:
        return ContactResultMeaning(
            next_human_step="observe_without_redispatch",
            status_explanation=(
                "A prepared intent exists but its outcome is not confirmed. Only observe "
                "or reconcile the existing action; do not prepare or dispatch another one."
            ),
        )
    return ContactResultMeaning(
        next_human_step="none",
        status_explanation={
            "rejected": "The human rejected the prepared action. No send or repeat is authorized.",
            "refused": (
                "Preparation produced a policy-refused audit record, not an eligible action. "
                "Neither approval nor another preparation is authorized by this result."
            ),
            "verified": (
                "The fake receiver accepted the prepared action. This is not real delivery "
                "or measured retention improvement. No repeat is authorized."
            ),
        }[status],
    )


def contact_result_output(result: ContactPreparationResult) -> str:
    return json.dumps(
        {
            **result.model_dump(mode="json"),
            "lifecycle": contact_result_meaning(result.status).model_dump(mode="json"),
        },
        ensure_ascii=False,
    )


class ContactContinueRequest(DomainModel):
    request_id: UUID
    confirmed: Literal[True]
    action_id: str = Field(min_length=1, max_length=100)
    action_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: int = Field(ge=0, strict=True)

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Literal confirmation is required")
        return value


class ContactContinuationView(DomainModel):
    turn_id: str
    status: Literal["reading", "thinking", "completed", "failed", "cancelled"]
    answer: str = Field(max_length=16000)
