"""Exact answers to a reminder's date question, not a general intent classifier."""

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


def reminder_date_answer(text: str, *, now: datetime, timezone: str) -> datetime | None:
    value = text.strip().casefold()
    zone = ZoneInfo(timezone)
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ t][0-9]{2}:[0-9]{2}(?::[0-9]{2})?", value):
        try:
            naive = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        match = re.fullmatch(
            r"(завтра|сегодня|ertaga|bugun|эртага|бугун|tomorrow|today)"
            r"\s+(?:(?:в|soat|соат|at)\s+)?([0-9]{1,2})(?::([0-9]{2}))?",
            value,
        )
        if match is None:
            return None
        day, hour, minute = match.groups()
        future = day in {"завтра", "ertaga", "эртага", "tomorrow"}
        date = now.astimezone(zone).date() + timedelta(days=int(future))
        try:
            naive = datetime.combine(date, datetime.min.time()).replace(
                hour=int(hour), minute=int(minute or 0)
            )
        except ValueError:
            return None
    result = naive.replace(tzinfo=zone)
    # Nonexistent or ambiguous wall times need an explicit unambiguous new request.
    if (
        result.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != naive
        or result.utcoffset() != naive.replace(tzinfo=zone, fold=1).utcoffset()
    ):
        return None
    return result
