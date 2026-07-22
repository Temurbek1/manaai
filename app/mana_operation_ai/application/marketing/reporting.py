import time
from collections.abc import Sequence
from datetime import datetime
from typing import cast

from pydantic import BaseModel, ConfigDict, JsonValue

from app.mana_operation_ai.domain.enums import ActionStatus, DataAvailability
from app.mana_operation_ai.domain.marketing import AdsSnapshot
from app.mana_operation_ai.domain.models import (
    ActionExecution,
    ActionProposal,
    AgentReport,
    Finding,
    Recommendation,
)


class NightlyMarketingReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_start: datetime
    period_end: datetime
    provider_mode: str
    api_version: str
    account: str
    currency: str
    timezone: str
    attribution_identity: str
    kpis: dict[str, str]
    best_creative: str
    weak_creatives: list[str]
    best_audiences: list[str]
    expensive_audiences: list[str]
    best_regions: list[str]
    inefficient_regions: list[str]
    best_placements: list[str]
    weak_placements: list[str]
    baseline_comparison: list[dict[str, str]]
    anomalies: list[str]
    actions: list[str]
    pending_approvals: list[str]
    failed_actions: list[str]
    next_recommendations: list[str]
    data_quality: list[str]
    compatibility: list[dict[str, object]]
    observability: dict[str, object]
    request_budget: dict[str, object] | None
    workflow_observability: dict[str, int | None]


class MarketingReportBuilder:
    def build(
        self,
        *,
        report_id: str,
        run_id: str,
        agent_id: str,
        snapshot: AdsSnapshot,
        findings: Sequence[Finding],
        recommendations: Sequence[Recommendation],
        proposals: Sequence[ActionProposal],
        executions: Sequence[ActionExecution],
        created_at: datetime,
        report_type: str = "nightly",
        analysis_duration_ms: int | None = None,
    ) -> AgentReport:
        report_started_at = time.perf_counter()
        metrics = _aggregate_snapshot(snapshot)
        report = NightlyMarketingReport(
            period_start=snapshot.period_start,
            period_end=snapshot.period_end,
            provider_mode=snapshot.provider_mode.value,
            api_version=snapshot.api_version or "unavailable",
            account=(snapshot.accounts[0].name if len(snapshot.accounts) == 1 else "unavailable"),
            currency=_single_account_value(
                [item.currency for item in snapshot.accounts],
            ),
            timezone=_single_account_value([item.timezone for item in snapshot.accounts]),
            attribution_identity=snapshot.attribution_window or "unavailable",
            kpis=metrics,
            best_creative=_first_title(findings, "best_creative") or "unavailable",
            weak_creatives=_titles(findings, "weak_creative"),
            best_audiences=_titles(findings, "cheap_audience"),
            expensive_audiences=_titles(findings, "expensive_audience"),
            best_regions=_titles(findings, "best_region"),
            inefficient_regions=_titles(findings, "inefficient_region"),
            best_placements=_titles(findings, "best_placement"),
            weak_placements=_titles(findings, "weak_placement"),
            baseline_comparison=_baseline_comparison(findings),
            anomalies=_titles(findings, "baseline_anomaly"),
            actions=[f"{item.status.value}: {item.proposal_id}" for item in executions],
            pending_approvals=[
                item.proposal_id
                for item in proposals
                if item.status is ActionStatus.AWAITING_APPROVAL
            ],
            failed_actions=[
                item.proposal_id
                for item in proposals
                if item.status in {ActionStatus.FAILED, ActionStatus.PARTIALLY_APPLIED}
            ],
            next_recommendations=[
                f"{item.action_type.value}: {item.provider_object_id} - {item.reasoning}"
                for item in recommendations
            ],
            data_quality=[
                *snapshot.data_quality_notes,
                *sorted({missing for item in findings for missing in item.missing_data}),
            ],
            compatibility=[item.model_dump(mode="json") for item in snapshot.compatibility_matrix],
            observability=snapshot.observability.model_dump(mode="json"),
            request_budget=(
                snapshot.request_budget.model_dump(mode="json")
                if snapshot.request_budget is not None
                else None
            ),
            workflow_observability={
                "analysis_duration_ms": analysis_duration_ms,
                "findings_count": len(findings),
                "recommendations_count": len(recommendations),
                "report_generation_duration_ms": 0,
            },
        )
        report.workflow_observability["report_generation_duration_ms"] = max(
            int((time.perf_counter() - report_started_at) * 1_000),
            0,
        )
        return AgentReport(
            report_id=report_id,
            agent_id=agent_id,
            run_id=run_id,
            report_type=report_type,
            period_start=snapshot.period_start,
            period_end=snapshot.period_end,
            structured=cast(dict[str, JsonValue], report.model_dump(mode="json")),
            human_readable=_human_readable(report),
            data_quality_notes=report.data_quality,
            created_at=created_at,
        )


def _aggregate_snapshot(snapshot: AdsSnapshot) -> dict[str, str]:
    from app.mana_operation_ai.application.marketing.analytics import aggregate_metrics

    metrics = aggregate_metrics(snapshot.insights)
    return {
        "spend": _metric_text(metrics.spend),
        "impressions": _metric_text(metrics.impressions),
        "reach": _metric_text(metrics.reach),
        "clicks": _metric_text(metrics.clicks),
        "leads": _metric_text(metrics.leads),
        "conversions": _metric_text(metrics.conversions),
        "ctr": _metric_text(metrics.ctr),
        "cpc": _metric_text(metrics.cpc),
        "cpm": _metric_text(metrics.cpm),
        "cpl": _metric_text(metrics.cpl),
        "cpa": _metric_text(metrics.cpa),
        "roas": _metric_text(metrics.roas),
    }


def _metric_text(metric: object) -> str:
    from app.mana_operation_ai.domain.marketing import Metric

    if not isinstance(metric, Metric) or metric.availability is DataAvailability.UNAVAILABLE:
        return "unavailable"
    return str(metric.value)


def _single_account_value(values: Sequence[str | None]) -> str:
    available = {value for value in values if value}
    return next(iter(available)) if len(available) == 1 else "unavailable"


def _baseline_comparison(findings: Sequence[Finding]) -> list[dict[str, str]]:
    comparisons: list[dict[str, str]] = []
    for finding in findings:
        for evidence in finding.evidence:
            if evidence.baseline is None:
                continue
            comparisons.append(
                {
                    "finding_id": finding.finding_id,
                    "metric": evidence.name,
                    "current": (
                        str(evidence.current.value)
                        if evidence.current.value is not None
                        else "unavailable"
                    ),
                    "baseline": (
                        str(evidence.baseline.value)
                        if evidence.baseline.value is not None
                        else "unavailable"
                    ),
                    "unit": evidence.current.unit,
                },
            )
    return comparisons


def _first_title(findings: Sequence[Finding], finding_type: str) -> str | None:
    return next((item.title for item in findings if item.finding_type == finding_type), None)


def _titles(findings: Sequence[Finding], finding_type: str) -> list[str]:
    return [item.title for item in findings if item.finding_type == finding_type]


def _human_readable(report: NightlyMarketingReport) -> str:
    kpis = report.kpis
    best = report.best_creative
    cpl = kpis.get("cpl", "unavailable")
    return "\n".join(
        [
            f"Marketing report: {report.period_start.date()} - {report.period_end.date()}",
            f"Mode: {report.provider_mode}; API: {report.api_version}",
            f"Account: {report.account}; currency/timezone: {report.currency}/{report.timezone}",
            f"Attribution: {report.attribution_identity}",
            f"Spend: {kpis.get('spend', 'unavailable')}",
            f"Impressions/reach/clicks: {kpis.get('impressions', 'unavailable')} / "
            f"{kpis.get('reach', 'unavailable')} / {kpis.get('clicks', 'unavailable')}",
            f"Leads/conversions: {kpis.get('leads', 'unavailable')} / "
            f"{kpis.get('conversions', 'unavailable')}",
            f"CTR: {kpis.get('ctr', 'unavailable')}; CPC: "
            f"{kpis.get('cpc', 'unavailable')}; CPM: {kpis.get('cpm', 'unavailable')}; "
            f"CPL: {cpl}; CPA: {kpis.get('cpa', 'unavailable')}; "
            f"ROAS: {kpis.get('roas', 'unavailable')}",
            f"Best creative: {best}",
            f"Pending approvals: {len(report.pending_approvals)}",
            f"Failed actions: {len(report.failed_actions)}",
            f"Data quality notes: {len(report.data_quality)}",
        ],
    )
