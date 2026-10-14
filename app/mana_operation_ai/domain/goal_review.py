"""A bounded review verdict, not rewritten evidence or a new execution permission."""

from typing import Annotated, Literal

from pydantic import Field, StrictBool, StringConstraints

from app.mana_operation_ai.domain.chat import ChatModel


class GoalReviewCheck(ChatModel):
    target: Literal["objective", "success_criteria"]
    quote: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(
        min_length=1, max_length=6000
    )
    status: Literal["passed", "failed", "not_checked"]
    finding: str = Field(max_length=1000)


class GoalReviewVerdictBody(ChatModel):
    input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    draft_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    checks: list[GoalReviewCheck] = Field(min_length=1, max_length=16)
    checked_plan_positions: list[Annotated[int, Field(ge=0, le=7, strict=True)]] = Field(
        max_length=8
    )
    conditions_checked: StrictBool
    evidence_checked: StrictBool
    evidence_ids: list[str] = Field(max_length=4)
    disposition: Literal["accepted", "revise", "waiting"]
    feedback: str = Field(min_length=1, max_length=2000)
