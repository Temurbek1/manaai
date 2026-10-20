"""Application-family agents, separate from the four operational administrators."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.mana_ai.domain.chat import (
    ChatContract,
    ParentChatHistory,
    ParentChatId,
    ParentChatRequest,
    ParentChatResponse,
)
from app.mana_ai.domain.enums import ManaAICapability

FamilyAgentId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{1,63}$", strict=True)]
InformationKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,99}$", strict=True)]
QuestionStatus = Literal[
    "queued", "offered", "awaiting_reply", "answered", "cancelled", "expired", "held"
]


class FamilyAgentDefinition(ChatContract):
    agent_id: FamilyAgentId
    title: str
    speaks_to_parent: bool
    capabilities: tuple[ManaAICapability, ...] = ()


class AgentQuestionRequest(ChatContract):
    """A specialist's intent, never a ready-to-send parent message or action grant."""

    parent_id: ParentChatId
    child_id: int = Field(gt=0, strict=True)
    agent_id: FamilyAgentId
    request_id: UUID
    information_key: InformationKey
    question: str = Field(min_length=1, max_length=400, pattern=r"\S")
    reason: str = Field(min_length=1, max_length=700, pattern=r"\S")
    source_revision: str = Field(min_length=1, max_length=128)
    priority: int = Field(default=1, ge=0, le=3, strict=True)
    observed_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def ordered_dates(self) -> "AgentQuestionRequest":
        if not 0 < (self.expires_at - self.observed_at).total_seconds() <= 7 * 86400:
            raise ValueError("A question needs an explicit validity window of at most seven days")
        return self


class FamilyQuestion(ChatContract):
    question_id: UUID
    parent_id: ParentChatId
    child_id: int = Field(gt=0, strict=True)
    information_key: InformationKey
    question: str
    reason: str
    priority: int = Field(ge=0, le=3, strict=True)
    status: QuestionStatus
    observed_at: AwareDatetime
    expires_at: AwareDatetime
    created_at: AwareDatetime
    offered_turn_id: int | None = None
    answer_turn_id: int | None = None


class AgentQuestionReceipt(ChatContract):
    request_id: UUID
    question: FamilyQuestion
    coalesced: bool


class AgentQuestionPage(ChatContract):
    parent_id: ParentChatId
    questions: list[FamilyQuestion]
    next_after: int | None = None


class ParentTouchRequest(ParentChatRequest):
    reply_to_question_id: UUID | None = None


class ParentTouchDeliveryRequest(ChatContract):
    parent_id: ParentChatId
    request_id: UUID


class ParentTouchDeliveryTurn(ParentChatRequest):
    """Host-only assistant turn; never persist a fabricated parent message."""

    message: Literal[""] = ""


class ParentTouchQuestion(ChatContract):
    question_id: UUID
    child_id: int = Field(gt=0, strict=True)
    turn_id: int = Field(gt=0, strict=True)


class ParentTouchResponse(ParentChatResponse):
    speaker: Literal["parent-touch"] = "parent-touch"
    asked_question: ParentTouchQuestion | None


class ParentTouchHistory(ParentChatHistory):
    speaker: Literal["parent-touch"] = "parent-touch"
    active_question: ParentTouchQuestion | None
    message_questions: list[ParentTouchQuestion]


class FamilyAgentAvailability(ChatContract):
    definition: FamilyAgentDefinition
    status: Literal["available", "disabled", "unavailable", "not_implemented"]


class FamilyAgentDirectory(ChatContract):
    agents: list[FamilyAgentAvailability]


class ParentTouchModelReply(ChatContract):
    body: str = Field(max_length=2000)
    question: str | None
    question_id: UUID | None

    @model_validator(mode="after")
    def one_question(self) -> "ParentTouchModelReply":
        if any(marker in self.body for marker in ("?", "؟", "？")):
            raise ValueError("Questions belong only in the single question field")
        if (self.question is None) != (self.question_id is None):
            raise ValueError("A question requires its exact admitted identity")
        if self.question is not None:
            if not 1 <= len(self.question.strip()) <= 400:
                raise ValueError("The parent-facing question must be bounded")
            if sum(self.question.count(marker) for marker in ("?", "؟", "？")) != 1:
                raise ValueError("A turn may contain only one explicit question")
            if not self.question.rstrip().endswith(("?", "؟", "？")):
                raise ValueError("The question must end at the question boundary")
        if not self.body.strip() and self.question is None:
            raise ValueError("A parent-facing reply cannot be empty")
        return self
