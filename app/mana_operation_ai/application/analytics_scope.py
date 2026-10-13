"""Explicit shared first-party evidence; no shared write or read-grant authority."""

from pydantic import ValidationError

from app.mana_operation_ai.domain.first_party_analytics import (
    CHILD_TELEMETRY_CAPABILITY,
    PARENT_ACTIVITY_CAPABILITY,
    ChildTelemetryFacts,
    ParentAnalyticsFacts,
)
from app.mana_operation_ai.domain.models import AgentReport


def shared_mana_analytics(report: AgentReport) -> bool:
    if (
        report.agent_id != "retention-agent"
        or report.report_type != "mana_first_party_analytics"
        or report.structured.get("product") != "mana"
        or report.structured.get("scope_verified") is not True
        or report.structured.get("scope_basis") != "approved_source_binding"
    ):
        return False
    contracts: dict[str, type[ParentAnalyticsFacts] | type[ChildTelemetryFacts]] = {
        PARENT_ACTIVITY_CAPABILITY: ParentAnalyticsFacts,
        CHILD_TELEMETRY_CAPABILITY: ChildTelemetryFacts,
    }
    contract = contracts.get(report.capability_key)
    if contract is None:
        return False
    expected = (
        ("mana_ga4_parent_analytics", "parent_app_analytics_identities")
        if report.capability_key == PARENT_ACTIVITY_CAPABILITY
        else ("mana_firestore_child_telemetry", "child_device_prefix_sample")
    )
    if (
        report.structured.get("source") != expected[0]
        or report.structured.get("population") != expected[1]
        or report.structured.get("product_scope") != "mana"
    ):
        return False
    payload = {
        key: value
        for key, value in report.structured.items()
        if key not in {"product", "scope_verified", "scope_basis"}
    }
    try:
        facts = contract.model_validate(payload)
    except ValidationError:
        return False
    return facts.product_scope.value == "mana"
