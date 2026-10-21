from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from app.mana_ai.domain.chat import (
    ChatQuota,
    ChatTokens,
    ParentChatHistory,
    ParentChatRequest,
    ParentChatResponse,
    ParentChildContext,
    ResponseLanguage,
    StoredChatTurn,
)
from app.mana_ai.domain.commercial_conversation import CommercialConversationContext
from app.mana_ai.domain.family_agents import (
    AgentQuestionPage,
    AgentQuestionReceipt,
    AgentQuestionRequest,
    FamilyNotice,
    FamilyQuestion,
    ParentTouchEvidence,
    ParentTouchHistory,
    ParentTouchNotice,
    ParentTouchQuestion,
)

ChatDecisionFailure = Literal[
    "provider_output_invalid", "reply_schema_invalid", "reply_language_mismatch"
]


class ParentChatError(Exception):
    def __init__(self, code: str, status_code: int, *, retry_after: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.retry_after = retry_after


class ChatModelRejected(Exception):
    """A definitive upstream rejection before inference, not an unknown receipt."""


@dataclass(frozen=True)
class ChatPrompt:
    instructions: str
    messages: tuple[tuple[str, str], ...]
    structured_reply: bool = False
    question: FamilyQuestion | None = None
    evidence_reply: bool = False
    notice: FamilyNotice | None = None
    minimum_output_tokens: int = 32
    slot_reply: bool = False
    safety_parent_review: bool = False
    response_language: ResponseLanguage | None = None


@dataclass(frozen=True)
class ChatModelReceipt:
    usage: ChatTokens
    model: str
    answer: str | None
    completed: bool
    question_id: UUID | None = None
    notice_id: UUID | None = None
    failure_code: ChatDecisionFailure | None = None


class ParentChatModel(Protocol):
    async def count_input(self, prompt: ChatPrompt) -> int: ...

    async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt: ...


class ParentChildrenSource(Protocol):
    async def read(self, parent_id: str) -> ParentChildContext: ...


class ParentChatStore(Protocol):
    async def admit(self, request: ParentChatRequest, now: datetime) -> StoredChatTurn: ...

    async def recent_completed(self, parent_id: str, limit: int) -> list[StoredChatTurn]: ...

    async def submit(
        self, turn: StoredChatTurn, *, reserved_tokens: int, now: datetime
    ) -> None: ...

    async def fail(
        self, turn: StoredChatTurn, *, code: str, status_code: int = 503, unknown: bool = False
    ) -> None: ...

    async def settle(
        self,
        turn: StoredChatTurn,
        *,
        receipt: ChatModelReceipt,
        now: datetime,
        history_turns: int,
        context_at: datetime,
    ) -> ParentChatResponse: ...

    async def history(
        self, parent_id: str, *, before: int | None, limit: int, now: datetime
    ) -> ParentChatHistory: ...

    async def quota(self, parent_id: str, now: datetime) -> ChatQuota: ...


class ParentTouchStore(ParentChatStore, Protocol):
    async def commercial_context(
        self, parent_id: str, turn_id: int
    ) -> CommercialConversationContext | None: ...

    async def language_hint(self, parent_id: str, turn_id: int) -> ResponseLanguage | None: ...
    async def evidence_for_turn(
        self, parent_id: str, turn_id: int, connected: tuple[int, ...]
    ) -> ParentTouchEvidence | None: ...
    async def delivered_notice(
        self, parent_id: str, request_id: UUID
    ) -> ParentTouchNotice | None: ...
    async def question_for_turn(self, parent_id: str, turn_id: int) -> FamilyQuestion | None: ...

    async def language_reference(self, parent_id: str, turn_id: int) -> str | None: ...

    async def asked_question(
        self, parent_id: str, request_id: UUID
    ) -> ParentTouchQuestion | None: ...

    async def touch_history(
        self, parent_id: str, *, before: int | None, limit: int, now: datetime
    ) -> ParentTouchHistory: ...

    async def claim_intent(
        self, request: AgentQuestionRequest, now: datetime
    ) -> AgentQuestionReceipt | None: ...

    async def finish_intent(
        self, request: AgentQuestionRequest, now: datetime
    ) -> AgentQuestionReceipt: ...

    async def fail_intent(self, request: AgentQuestionRequest, error: ParentChatError) -> None: ...

    async def questions(
        self, parent_id: str, *, after: int | None = None, limit: int = 20
    ) -> AgentQuestionPage: ...
