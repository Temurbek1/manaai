"""Minimized, MANA-only parent inventory; never a payment or churn ledger."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.mana_operation_ai.domain.models import DomainModel


class ParentSummaryConfiguration(DomainModel):
    product: Literal["mana"] = "mana"


class ParentSummary(DomainModel):
    product: Literal["mana"] = "mana"
    scope_verified: Literal[True] = True
    scope_basis: Literal["owner_confirmed_parent_api"] = "owner_confirmed_parent_api"
    source: str
    mode: Literal["live_read_only", "demo"]
    collected_at: datetime
    total_parents: int = Field(ge=0)
    sampled_parents: int = Field(ge=0)
    has_more: bool
    parents_with_name: int = Field(ge=0)
    parents_with_phone: int = Field(ge=0)
    parents_with_known_age: int = Field(ge=0)
    parents_with_region: int = Field(ge=0)
    parents_with_district: int = Field(ge=0)
    parents_with_current_tariff: int = Field(ge=0)
    parents_without_current_tariff: int = Field(ge=0)
    parents_with_inconsistent_tariff: int = Field(ge=0)
    tariffs_expiring_within_7_days: int = Field(ge=0)
    tariffs_expiring_within_30_days: int = Field(ge=0)
    parents_with_purchase_date: int = Field(ge=0)
    parents_with_children: int = Field(ge=0)
    parents_with_connected_children: int = Field(ge=0)
    child_relationships_observed: int = Field(ge=0)
    connected_child_relationships: int = Field(ge=0)
    source_request_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
