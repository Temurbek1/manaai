from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter


def next_cron_occurrence(expression: str, timezone: str, after: datetime) -> datetime:
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone {timezone!r}") from exc
    if after.tzinfo is None:
        raise ValueError("Scheduler timestamps must be timezone-aware")
    if not croniter.is_valid(expression):
        raise ValueError("Invalid cron expression")
    candidate = after.astimezone(UTC).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(60 * 24 * 366 * 5):
        local_candidate = candidate.astimezone(zone)
        local_wall_time = local_candidate.replace(tzinfo=None)
        if local_candidate.fold == 0 and croniter.match(expression, local_wall_time):
            return candidate.astimezone(after.tzinfo)
        candidate += timedelta(minutes=1)
    raise ValueError("Cron expression has no occurrence in the next five years")
