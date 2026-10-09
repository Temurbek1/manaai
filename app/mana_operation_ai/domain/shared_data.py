from datetime import datetime
from typing import Literal

from pydantic import Field

from app.mana_operation_ai.domain.cost_control import ProductScope
from app.mana_operation_ai.domain.models import DomainModel


class CollectedAggregate(DomainModel):
    collected_at: datetime
    limitations: list[str] = Field(default_factory=list)
    product_scope: ProductScope = ProductScope.UNVERIFIED
    fresh_until: datetime | None = None
    refresh_status: Literal["live", "cached", "stale"] = "live"


class SourceBinding(DomainModel):
    """Approved source identity; never infer application ownership from credentials."""

    product: ProductScope
    source: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_.-]+$")
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    minimum_interval_seconds: int = Field(default=21_600, ge=21_600)
    lease_seconds: int = Field(default=1_800, ge=30, le=3_600)


class SavedAggregate(DomainModel):
    query_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    collected_at: datetime
    fresh_until: datetime
    payload: dict[str, object]


class SourceAdmission(DomainModel):
    binding_key: str
    query_key: str
    token: str | None = None
    snapshot: SavedAggregate | None = None
    reason: Literal["admitted", "fresh", "cooldown", "busy", "blocked"]
