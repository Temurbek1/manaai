"""User-selectable inference settings, separate from tool and action authority."""

from typing import Literal

ModelChoice = Literal["auto", "gpt-5.4-mini", "gpt-6.1-sol", "gpt-6-astra"]
ReasoningChoice = Literal["auto", "low", "medium", "high"]
