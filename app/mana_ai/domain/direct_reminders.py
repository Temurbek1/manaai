"""A captured explicit reminder request selects an owner, never schedules an action."""

from typing import Literal

from pydantic import AwareDatetime

from app.mana_ai.domain.chat import ChatContract
from app.mana_ai.domain.parent_reminders import ReminderCandidate


class DirectReminderRequest(ChatContract):
    protocol: Literal[1] = 1
    captured_at: AwareDatetime
    timezone_basis: Literal[
        "verified_contact",
        "application_default_requires_confirmation",
        "parent_explicit_requires_confirmation",
    ]
    candidate: ReminderCandidate
