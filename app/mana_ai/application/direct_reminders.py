"""Full-message literal routing; semantic acceptance still belongs to the strong model."""

import re
from datetime import datetime
from typing import Literal, Protocol

from app.mana_ai.application.reminder_dates import reminder_date_answer
from app.mana_ai.domain.direct_reminders import DirectReminderRequest
from app.mana_ai.domain.parent_reminders import ReminderCandidate

_DAY = r"(?:[0-9]{4}-[0-9]{2}-[0-9]{2}|сегодня|завтра|bugun|ertaga|бугун|эртага|today|tomorrow)"
_TIME = r"[0-9]{1,2}:[0-9]{2}"
_ZONE = r"(?:UTC|GMT|[A-Za-z_]+(?:/[A-Za-z0-9_+\-]+)+)"
_REQUEST = re.compile(
    r"(?P<command>напомни(?: мне)?|remind me|eslat(?: menga)?|эслат(?: менга)?)\s+"
    rf"(?P<day>{_DAY})\s+(?:(?:в|at|soat|соат)\s+)?(?P<time>{_TIME})"
    r"(?:\s+(?:(?:по часовому поясу|timezone|vaqt mintaqasi|вақт минтақаси)\s+)?"
    rf"(?P<zone>{_ZONE}))?"
    r"\s+(?:to\s+)?(?P<task>[^\r\n!?;]{1,250})",
    re.IGNORECASE,
)
_UZ_REQUEST = re.compile(
    rf"(?P<day>{_DAY})\s+(?:soat|соат)\s+(?P<time>{_TIME})(?:da|да)?\s+"
    r"(?P<task>[^\r\n!?;]{1,250})\s+(?:eslat|эслат)",
    re.IGNORECASE,
)


class DirectReminderPort(Protocol):
    async def direct_reminder_request(
        self, parent_id: str, turn_id: int
    ) -> DirectReminderRequest | None: ...


def direct_reminder_request(
    message: str,
    *,
    now: datetime,
    timezone: str,
    timezone_basis: Literal["verified_contact", "application_default_requires_confirmation"],
) -> DirectReminderRequest | None:
    match = _REQUEST.fullmatch(message.strip()) or _UZ_REQUEST.fullmatch(message.strip())
    if match is None:
        return None
    task = match["task"].strip()
    # Multi-sentence/mixed requests and unfamiliar grammar retain full model routing.
    if not task or "." in task.removesuffix(".") or ":" in task:
        return None
    explicit_zone = match.groupdict().get("zone")
    if explicit_zone is None and re.match(r"^[A-Za-z_]+/[^\s]+(?:\s|$)", task):
        return None
    if explicit_zone is None and re.match(r"^[A-Z]{2,5}(?:[+-][0-9]{1,2})?(?:\s|$)", task):
        return None
    if explicit_zone is None and task.casefold().startswith(
        ("timezone ", "по часовому поясу ", "vaqt mintaqasi ", "вақт минтақаси ")
    ):
        return None
    zone = explicit_zone or timezone
    try:
        date = reminder_date_answer(match["day"] + " " + match["time"], now=now, timezone=zone)
        if date is None:
            return None
        return DirectReminderRequest(
            captured_at=now,
            timezone_basis="parent_explicit_requires_confirmation"
            if explicit_zone
            else timezone_basis,
            candidate=ReminderCandidate(content=task, due_at=date, timezone=zone),
        )
    except (ValueError, KeyError):
        return None
