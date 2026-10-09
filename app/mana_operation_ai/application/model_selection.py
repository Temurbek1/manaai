"""Deterministic routing: trivial conversation is cheap; analysis gets reasoning."""

import re
from dataclasses import dataclass
from typing import Literal

from app.mana_operation_ai.domain.inference import ModelChoice, ReasoningChoice


@dataclass(frozen=True)
class InferencePlan:
    model: str
    effort: Literal["low", "medium", "high"]


def select_inference(
    *, model_choice: ModelChoice, reasoning: ReasoningChoice, message: str, goal: bool
) -> InferencePlan:
    # Only whole, genuinely trivial messages route down. Length alone is not a
    # complexity estimate: "why is revenue falling?" needs the strong model.
    trivial = re.fullmatch(
        r"(?:привет|здравствуй(?:те)?|спасибо|благодарю|hello|hi|thanks)[.!\s]*",
        message.strip(),
        flags=re.IGNORECASE,
    )
    model = (
        ("gpt-5.4-mini" if trivial and not goal else "gpt-6.1-sol")
        if model_choice == "auto"
        else model_choice
    )
    effort: Literal["low", "medium", "high"] = (
        ("medium" if goal or model != "gpt-5.4-mini" else "low")
        if reasoning == "auto"
        else reasoning
    )
    return InferencePlan(model=model, effort=effort)
