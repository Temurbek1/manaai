"""Resolve trusted runtime choices against deployment-owned rate cards."""

import json

from pydantic import BaseModel, ConfigDict

from app.core.config import Settings
from app.mana_operation_ai.application.model_selection import InferencePlan, select_inference
from app.mana_operation_ai.domain.cost_control import LlmRateCard
from app.mana_operation_ai.domain.inference import ModelChoice, ReasoningChoice


class InferenceOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_choice: ModelChoice = "auto"
    reasoning: ReasoningChoice = "auto"


def inference_rate_cards(settings: Settings) -> dict[str, LlmRateCard]:
    names = ("gpt-5.4-mini", "gpt-6.1-sol", "gpt-6-astra")
    if set(settings.operation_inference_rate_cards) != set(names):
        raise ValueError("Inference catalog requires all three supported model rate cards")
    return {
        name: LlmRateCard.model_validate(
            {**settings.operation_inference_rate_cards[name], "model": name}
        )
        for name in names
    }


def selected_inference(context: str, *, goal: bool) -> InferencePlan:
    payload = json.loads(context)
    raw_options = (
        {
            key: value
            for key, value in payload.get("goal", {}).get("request", {}).items()
            if key in {"model_choice", "reasoning"}
        }
        if goal
        else payload.get("inference", {})
    )
    options = InferenceOptions.model_validate(raw_options)
    return select_inference(
        model_choice=options.model_choice,
        reasoning=options.reasoning,
        message=payload.get("message", ""),
        goal=goal,
    )
