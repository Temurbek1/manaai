from datetime import datetime, timedelta

from app.mana_operation_ai.domain.models import DataSnapshot


def evidence_freshness_failure(
    snapshots: list[DataSnapshot], *, now: datetime, maximum_age_seconds: int
) -> str | None:
    """Validate saved evidence independently of provider target-state validation."""
    if maximum_age_seconds < 1 or now.utcoffset() is None:
        raise ValueError("Evidence freshness requires a positive age and aware clock")
    if not snapshots:
        return "No source evidence exists for this action run"
    for snapshot in snapshots:
        if snapshot.collected_at.utcoffset() is None or snapshot.collected_at > now:
            return "Source evidence has an invalid collection time"
        status = snapshot.payload.get("refresh_status")
        if status is not None and status not in ("live", "cached"):
            return "Source evidence is stale or refresh availability is unknown"
        scope = snapshot.payload.get("product_scope")
        if scope is not None and scope not in ("mana", "360rec"):
            return "Source evidence has no verified application scope"
        expires = snapshot.collected_at + timedelta(seconds=maximum_age_seconds)
        declared_expiry = snapshot.payload.get("fresh_until")
        if declared_expiry is not None:
            if not isinstance(declared_expiry, str):
                return "Source evidence has an invalid freshness deadline"
            try:
                parsed = datetime.fromisoformat(declared_expiry)
            except ValueError:
                return "Source evidence has an invalid freshness deadline"
            if parsed.utcoffset() is None:
                return "Source evidence freshness deadline must be timezone-aware"
            expires = min(expires, parsed)
        if now >= expires:
            return "Source evidence is too old; request an admitted refresh before acting"
    scopes = {
        snapshot.payload.get("product_scope")
        for snapshot in snapshots
        if isinstance(snapshot.payload.get("product_scope"), str)
    }
    if len(scopes) > 1:
        return "Action evidence mixes different applications"
    return None
