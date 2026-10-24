"""Application-family agents, separate from the four operational administrators."""

import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.mana_ai.domain.chat import (
    ChatContract,
    ParentChatHistory,
    ParentChatId,
    ParentChatRequest,
    ParentChatResponse,
    StoredChatTurn,
)
from app.mana_ai.domain.enums import (
    AnalysisStatus,
    AnalysisVerdict,
    FindingCategory,
    ManaAICapability,
    RiskLevel,
)
from app.mana_ai.domain.family_sources import ChildAppUsageFacts, ChildBatteryFacts

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


class ParentTouchMessageRequest(ChatContract):
    """Review-first parent text; new sensor observations use the protective endpoints."""

    parent_id: ParentChatId
    request_id: UUID
    message: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    reply_to_question_id: UUID | None = None


class ParentTouchReviewedTurn(ParentTouchRequest):
    """Host-captured protocol, never added to an already admitted synchronous turn."""

    protocol: Literal["review-first-v1"] = "review-first-v1"


class ParentTouchReviewGuidance(ChatContract):
    summary: str = Field(min_length=1, max_length=1500)
    reviewed_at: AwareDatetime
    parent_message_at: AwareDatetime
    authorized_child_ids: tuple[int, ...]
    source_observations: tuple[ChildBatteryFacts | ChildAppUsageFacts, ...] = Field(
        default=(), max_length=1, exclude_if=lambda value: not value
    )


class ReviewedMessage(ChatContract):
    turn: StoredChatTurn
    phase: Literal["awaiting_review", "responding", "completed", "failed", "unknown"]


class ParentTouchDeliveryRequest(ChatContract):
    parent_id: ParentChatId
    request_id: UUID
    resume_deferred_request_id: UUID | None = None


class ParentTouchDeliveryTurn(ParentChatRequest):
    """Host-only assistant turn; never persist a fabricated parent message."""

    message: Literal[""] = ""


class ParentTouchDeferredTurn(ParentTouchDeliveryTurn):
    """New backend intent, never replay of the original refused delivery."""

    resume_deferred_request_id: UUID


class ParentTouchQuestion(ChatContract):
    question_id: UUID
    child_id: int = Field(gt=0, strict=True)
    turn_id: int = Field(gt=0, strict=True)


class ParentTouchNotice(ChatContract):
    notice_id: UUID
    child_id: int = Field(gt=0, strict=True)
    turn_id: int = Field(gt=0, strict=True)
    kind: Literal["assessment", "urgent"]


class ParentTouchFinding(ChatContract):
    category: FindingCategory
    risk_level: RiskLevel
    summary: str
    recommendation: str


class ParentTouchAssessment(ChatContract):
    assessment_id: UUID
    child_id: int = Field(gt=0, strict=True)
    capability: ManaAICapability
    status: AnalysisStatus
    verdict: AnalysisVerdict
    summary: str
    data_quality_notes: list[str]
    evaluated_at: AwareDatetime | None
    signal_first_observed_at: AwareDatetime | None
    signal_last_observed_at: AwareDatetime | None
    processed_at: AwareDatetime
    significant_findings: list[ParentTouchFinding] = Field(default_factory=list, max_length=1)
    available_finding_count: int = Field(default=0, ge=0, strict=True)


class FamilyNotice(ChatContract):
    notice_id: UUID
    parent_id: ParentChatId
    agent_id: FamilyAgentId
    kind: Literal["assessment", "urgent"]
    assessment: ParentTouchAssessment
    expires_at: AwareDatetime


class ParentTouchEvidence(ChatContract):
    protocol: Literal["assessment-context-v1"] = "assessment-context-v1"
    assessments: list[ParentTouchAssessment] = Field(max_length=1)
    available_assessment_count: int = Field(ge=0, strict=True)
    notice: FamilyNotice | None = None


class ParentTouchResponse(ParentChatResponse):
    speaker: Literal["parent-touch"] = "parent-touch"
    asked_question: ParentTouchQuestion | None
    delivered_notice: ParentTouchNotice | None = None


class ParentTouchMessageState(ChatContract):
    parent_id: ParentChatId
    request_id: UUID
    turn_id: int
    phase: Literal["awaiting_review", "responding", "completed", "failed", "unknown"]
    error_code: str | None = None
    response: ParentTouchResponse | None = None


class ParentTouchHistory(ParentChatHistory):
    speaker: Literal["parent-touch"] = "parent-touch"
    active_question: ParentTouchQuestion | None
    message_questions: list[ParentTouchQuestion]
    message_notices: list[ParentTouchNotice] = Field(default_factory=list)
    pending_notices: int = 0


class FamilyAgentAvailability(ChatContract):
    definition: FamilyAgentDefinition
    status: Literal["available", "disabled", "unavailable", "not_implemented"]


class FamilyAgentDirectory(ChatContract):
    agents: list[FamilyAgentAvailability]


class ParentTouchText(ChatContract):
    body: str = Field(
        max_length=2000,
        pattern=r"^[^?؟？]*$",
        description="Statements only. The single admitted question belongs in question, not body.",
    )
    question: str | None

    @model_validator(mode="after")
    def one_question(self) -> "ParentTouchText":
        for text in (self.body, self.question or ""):
            if (
                re.search(r"\b(?:question|notice|parent|child)(?:_|[ -]+)id\b", text, re.I)
                or re.search(r"\b(?:reply_to_question_id|notice_communicated)\b", text, re.I)
                or re.search(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", text, re.I)
            ):
                raise ValueError("Internal routing metadata is not parent-facing text")
        if any(marker in self.body for marker in ("?", "؟", "？")):
            raise ValueError("Questions belong only in the single question field")
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


class ParentTouchModelReply(ParentTouchText):
    question_id: UUID | None

    @model_validator(mode="after")
    def admitted_identity(self) -> "ParentTouchModelReply":
        if (self.question is None) != (self.question_id is None):
            raise ValueError("A question requires its exact admitted identity")
        return self


class ParentTouchEvidenceReply(ParentTouchModelReply):
    notice_id: UUID | None


class ParentTouchSlotReply(ParentTouchText):
    """Language generation cannot choose identities; the host owns the sole admitted slots."""

    notice_communicated: bool = Field(strict=True)
