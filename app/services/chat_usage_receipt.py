"""Strict uncoerced terminal usage, shared by ordinary and native family transport."""

from app.mana_ai.domain.chat import ChatTokens


def terminal_chat_usage(payload: object) -> ChatTokens:
    if not isinstance(payload, dict) or payload.get("status") not in {
        "completed",
        "incomplete",
        "failed",
        "cancelled",
    }:
        raise ValueError("Missing terminal parent chat receipt")
    usage = payload.get("usage")
    if (
        not isinstance(usage, dict)
        or any(
            type(usage.get(key)) is not int or not 0 <= usage[key] <= 2**31 - 1
            for key in ("input_tokens", "output_tokens", "total_tokens")
        )
        or usage["input_tokens"] + usage["output_tokens"] != usage["total_tokens"]
    ):
        raise ValueError("Invalid parent chat usage receipt")
    return ChatTokens(input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"])
