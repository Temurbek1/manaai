from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.mana_operation_ai.application.marketing.metrics import build_metrics
from app.mana_operation_ai.application.ports import IdGenerator
from app.mana_operation_ai.domain.enums import (
    ActionType,
    DataAvailability,
    FindingSeverity,
)
from app.mana_operation_ai.domain.marketing import (
    AdEntity,
    AdsSnapshot,
    InsightRow,
    MarketingAgentConfiguration,
    MarketingObjective,
    Metric,
    PerformanceMetrics,
)
from app.mana_operation_ai.domain.models import (
    Analysis,
    AudienceActionParameters,
    BudgetActionParameters,
    EvidenceMetric,
    Finding,
    MetricValue,
    NoChangeActionParameters,
    Recommendation,
    StatusActionParameters,
    TestProposalParameters,
)


class MarketingAnalysisBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis: Analysis
    findings: list[Finding]
    recommendations: list[Recommendation]


class MarketingAnalyticsEngine:
    def __init__(self, *, ids: IdGenerator) -> None:
        self._ids = ids

    def analyze(
        self,
        *,
        run_id: str,
        snapshot_id: str,
        snapshot: AdsSnapshot,
        configuration: MarketingAgentConfiguration,
        now: datetime,
    ) -> MarketingAnalysisBundle:
        effective_end = snapshot.period_end.date() - timedelta(
            days=configuration.conversion_lag_days,
        )
        current_start = effective_end - timedelta(
            days=configuration.comparison_period_days - 1,
        )
        current_rows = [
            row for row in snapshot.insights if current_start <= row.date_stop <= effective_end
        ]
        baseline_rows = [
            row
            for row in snapshot.insights
            if row.date_stop < current_start and row.date_stop <= effective_end
        ]
        current_metrics = aggregate_metrics(current_rows)
        baseline_metrics = aggregate_metrics(baseline_rows)
        analysis_id = self._ids.new()
        quality_score = data_quality_score(snapshot, current_rows)
        analysis = Analysis(
            analysis_id=analysis_id,
            run_id=run_id,
            snapshot_id=snapshot_id,
            calculated_at=now,
            metrics=metrics_for_analysis(current_metrics),
            baseline_metrics=metrics_for_analysis(baseline_metrics),
            data_quality_score=quality_score,
            notes=[
                *snapshot.data_quality_notes,
                *period_coverage_notes(
                    current_rows,
                    baseline_rows,
                    configuration,
                ),
                *availability_notes(current_metrics),
            ],
        )
        findings = self._findings(
            run_id=run_id,
            analysis_id=analysis_id,
            snapshot=snapshot,
            current_rows=current_rows,
            baseline_rows=baseline_rows,
            configuration=configuration,
            now=now,
        )
        if quality_score < configuration.data_completeness_threshold and not any(
            item.finding_type == "insufficient_data" for item in findings
        ):
            findings.append(
                self._finding(
                    run_id=run_id,
                    analysis_id=analysis_id,
                    finding_type="data_quality_warning",
                    severity=FindingSeverity.WARNING,
                    title="Data completeness is below the configured threshold",
                    description=(
                        "Deterministic data-quality score is below the calibrated minimum; "
                        "recommendations require additional caution."
                    ),
                    object_type=None,
                    provider_object_id=None,
                    dimensions={},
                    evidence=[
                        EvidenceMetric(
                            name="data_quality_score",
                            current=MetricValue(
                                value=quality_score,
                                unit="ratio",
                                availability=DataAvailability.AVAILABLE,
                            ),
                            baseline=MetricValue(
                                value=configuration.data_completeness_threshold,
                                unit="ratio",
                                availability=DataAvailability.AVAILABLE,
                            ),
                        ),
                    ],
                    confidence=Decimal("1"),
                    missing_data=analysis.notes,
                    now=now,
                ),
            )
        currency_values = currencies_for(current_rows)
        source_currency = next(iter(currency_values)) if len(currency_values) == 1 else None
        baseline_end = current_start - timedelta(days=1)
        baseline_start = baseline_end - timedelta(
            days=configuration.baseline_period_days - 1,
        )
        contextual_findings: list[Finding] = []
        for finding in findings:
            limitations = sorted({*snapshot.data_quality_notes, *finding.missing_data})
            contextual_findings.append(
                finding.model_copy(
                    update={
                        "source_snapshot_id": snapshot_id,
                        "period_start": snapshot.period_start,
                        "period_end": snapshot.period_end,
                        "attribution_identity": snapshot.attribution_window,
                        "currency": source_currency,
                        "deterministic_calculation": (
                            "Normalized metrics, configured thresholds, and deterministic "
                            "ranking; exact operands are preserved in evidence."
                        ),
                        "baseline_period_start": datetime.combine(
                            baseline_start,
                            datetime.min.time(),
                            tzinfo=snapshot.period_start.tzinfo,
                        ),
                        "baseline_period_end": datetime.combine(
                            baseline_end,
                            datetime.max.time(),
                            tzinfo=snapshot.period_end.tzinfo,
                        ),
                        "completeness": quality_score,
                        "limitations": limitations,
                    },
                ),
            )
        findings = contextual_findings
        recommendations = self._recommendations(
            run_id=run_id,
            snapshot=snapshot,
            current_rows=current_rows,
            findings=findings,
            configuration=configuration,
            now=now,
        )
        return MarketingAnalysisBundle(
            analysis=analysis,
            findings=findings,
            recommendations=recommendations,
        )

    def _findings(
        self,
        *,
        run_id: str,
        analysis_id: str,
        snapshot: AdsSnapshot,
        current_rows: list[InsightRow],
        baseline_rows: list[InsightRow],
        configuration: MarketingAgentConfiguration,
        now: datetime,
    ) -> list[Finding]:
        if not current_rows:
            return [
                self._finding(
                    run_id=run_id,
                    analysis_id=analysis_id,
                    finding_type="insufficient_data",
                    severity=FindingSeverity.WARNING,
                    title="No current performance data",
                    description="No current insight rows are available for a confident decision.",
                    object_type=None,
                    provider_object_id=None,
                    dimensions={},
                    evidence=[],
                    confidence=Decimal("1"),
                    missing_data=["current insights"],
                    now=now,
                ),
            ]

        currencies = currencies_for(current_rows)
        attribution_windows = {row.attribution_window for row in current_rows}
        if len(attribution_windows) > 1:
            return [
                self._finding(
                    run_id=run_id,
                    analysis_id=analysis_id,
                    finding_type="mixed_attribution_windows",
                    severity=FindingSeverity.WARNING,
                    title="Insight rows use different attribution windows",
                    description=(
                        "Performance rankings and actions are suppressed because attribution "
                        "windows cannot be combined deterministically."
                    ),
                    object_type=None,
                    provider_object_id=None,
                    dimensions={"windows": ",".join(sorted(attribution_windows))},
                    evidence=[],
                    confidence=Decimal("1"),
                    missing_data=["one consistent attribution window"],
                    now=now,
                ),
            ]
        if any(row.currency is None for row in current_rows):
            return [
                self._finding(
                    run_id=run_id,
                    analysis_id=analysis_id,
                    finding_type="currency_unavailable",
                    severity=FindingSeverity.WARNING,
                    title="Currency metadata is unavailable",
                    description=(
                        "Financial rankings and actions are suppressed because at least one "
                        "Insight row has no verified account currency."
                    ),
                    object_type=None,
                    provider_object_id=None,
                    dimensions={},
                    evidence=[],
                    confidence=Decimal("1"),
                    missing_data=["ad account currency"],
                    now=now,
                ),
            ]
        if len(currencies) > 1:
            return [
                self._finding(
                    run_id=run_id,
                    analysis_id=analysis_id,
                    finding_type="mixed_currency_data",
                    severity=FindingSeverity.WARNING,
                    title="Monetary results span multiple currencies",
                    description=(
                        "Spend and cost rankings are suppressed because currencies cannot be "
                        "combined without an explicit conversion source."
                    ),
                    object_type=None,
                    provider_object_id=None,
                    dimensions={"currencies": ",".join(sorted(currencies))},
                    evidence=[],
                    confidence=Decimal("1"),
                    missing_data=["trusted currency conversion rates"],
                    now=now,
                ),
            ]

        findings: list[Finding] = []
        findings.extend(
            self._ranked_dimension_findings(
                run_id=run_id,
                analysis_id=analysis_id,
                rows=current_rows,
                baseline_rows=baseline_rows,
                key="creative_id",
                object_type="creative",
                best_type="best_creative",
                worst_type="weak_creative",
                best_title="Best-performing creative",
                worst_title="Weak creative",
                configuration=configuration,
                now=now,
            ),
        )
        findings.extend(
            self._ranked_dimension_findings(
                run_id=run_id,
                analysis_id=analysis_id,
                rows=current_rows,
                baseline_rows=baseline_rows,
                key="audience_id",
                object_type="audience",
                best_type="cheap_audience",
                worst_type="expensive_audience",
                best_title="Lowest-cost audience",
                worst_title="Expensive audience",
                configuration=configuration,
                now=now,
            ),
        )
        for dimension, best_type, worst_type, label in [
            ("region", "best_region", "wasteful_region", "region"),
            ("placement", "best_placement", "weak_placement", "placement"),
            ("hour", "best_hour", "weak_hour", "hour"),
            ("day", "best_day", "weak_day", "day"),
        ]:
            findings.extend(
                self._ranked_dimension_findings(
                    run_id=run_id,
                    analysis_id=analysis_id,
                    rows=current_rows,
                    baseline_rows=baseline_rows,
                    key=dimension,
                    object_type=label,
                    best_type=best_type,
                    worst_type=worst_type,
                    best_title=f"Best-performing {label}",
                    worst_title=f"Weakest {label}",
                    configuration=configuration,
                    now=now,
                    dimension=True,
                ),
            )

        findings.extend(
            self._budget_findings(
                run_id=run_id,
                analysis_id=analysis_id,
                snapshot=snapshot,
                current_rows=current_rows,
                configuration=configuration,
                now=now,
            ),
        )
        findings.extend(
            self._fatigue_and_anomaly_findings(
                run_id=run_id,
                analysis_id=analysis_id,
                current_rows=current_rows,
                baseline_rows=baseline_rows,
                configuration=configuration,
                now=now,
            ),
        )
        missing_dimensions = [
            dimension.value
            for dimension in configuration.requested_breakdowns
            if not any(dimension.value in row.dimensions for row in current_rows)
        ]
        if missing_dimensions:
            findings.append(
                self._finding(
                    run_id=run_id,
                    analysis_id=analysis_id,
                    finding_type="insufficient_data",
                    severity=FindingSeverity.INFO,
                    title="Some requested breakdowns are unavailable",
                    description="Provider data cannot support every requested comparison.",
                    object_type=None,
                    provider_object_id=None,
                    dimensions={},
                    evidence=[],
                    confidence=Decimal("1"),
                    missing_data=missing_dimensions,
                    now=now,
                ),
            )
        coverage_notes = period_coverage_notes(
            current_rows,
            baseline_rows,
            configuration,
        )
        if coverage_notes:
            findings.append(
                self._finding(
                    run_id=run_id,
                    analysis_id=analysis_id,
                    finding_type="incomplete_period_coverage",
                    severity=FindingSeverity.INFO,
                    title="Analysis periods are incomplete",
                    description="Not every configured comparison or baseline day is represented.",
                    object_type=None,
                    provider_object_id=None,
                    dimensions={},
                    evidence=[],
                    confidence=Decimal("1"),
                    missing_data=coverage_notes,
                    now=now,
                ),
            )
        return findings

    def _ranked_dimension_findings(
        self,
        *,
        run_id: str,
        analysis_id: str,
        rows: Sequence[InsightRow],
        baseline_rows: Sequence[InsightRow],
        key: str,
        object_type: str,
        best_type: str,
        worst_type: str,
        best_title: str,
        worst_title: str,
        configuration: MarketingAgentConfiguration,
        now: datetime,
        dimension: bool = False,
    ) -> list[Finding]:
        grouped = group_rows(rows, key=key, dimension=dimension)
        candidates = [
            (group_key, group_rows_value, aggregate_metrics(group_rows_value))
            for group_key, group_rows_value in grouped.items()
            if group_key
            and has_minimum_observation(
                aggregate_metrics(group_rows_value),
                configuration,
            )
        ]
        candidates = [item for item in candidates if cost_value(item[2], configuration) is not None]
        if not candidates:
            return []
        ordered = sorted(
            candidates,
            key=lambda item: cost_value(item[2], configuration) or Decimal("Infinity"),
        )
        best = ordered[0]
        worst = ordered[-1]
        results = [
            self._performance_finding(
                run_id=run_id,
                analysis_id=analysis_id,
                finding_type=best_type,
                title=best_title,
                object_type=object_type,
                provider_object_id=best[0],
                rows=best[1],
                baseline_rows=group_rows(baseline_rows, key=key, dimension=dimension).get(
                    best[0],
                    [],
                ),
                metrics=best[2],
                severity=FindingSeverity.INFO,
                dimensions={key: best[0]} if dimension else {},
                configuration=configuration,
                now=now,
            ),
        ]
        if worst[0] != best[0]:
            results.append(
                self._performance_finding(
                    run_id=run_id,
                    analysis_id=analysis_id,
                    finding_type=worst_type,
                    title=worst_title,
                    object_type=object_type,
                    provider_object_id=worst[0],
                    rows=worst[1],
                    baseline_rows=group_rows(
                        baseline_rows,
                        key=key,
                        dimension=dimension,
                    ).get(worst[0], []),
                    metrics=worst[2],
                    severity=FindingSeverity.WARNING,
                    dimensions={key: worst[0]} if dimension else {},
                    configuration=configuration,
                    now=now,
                ),
            )
        return results

    def _performance_finding(
        self,
        *,
        run_id: str,
        analysis_id: str,
        finding_type: str,
        title: str,
        object_type: str,
        provider_object_id: str,
        rows: Sequence[InsightRow],
        baseline_rows: Sequence[InsightRow],
        metrics: PerformanceMetrics,
        severity: FindingSeverity,
        dimensions: dict[str, str],
        configuration: MarketingAgentConfiguration,
        now: datetime,
    ) -> Finding:
        cost_name, cost = objective_cost(metrics, configuration)
        baseline = aggregate_metrics(baseline_rows)
        baseline_cost = metric_by_name(baseline, cost_name)
        evidence = [
            EvidenceMetric(
                name=cost_name,
                current=core_metric(cost, "currency/result"),
                baseline=core_metric(baseline_cost, "currency/result"),
            ),
            EvidenceMetric(name="spend", current=core_metric(metrics.spend, "currency")),
            EvidenceMetric(name="ctr", current=core_metric(metrics.ctr, "percent")),
            EvidenceMetric(name="frequency", current=core_metric(metrics.frequency, "ratio")),
        ]
        entity_label = rows[0].entity_name if rows else provider_object_id
        return self._finding(
            run_id=run_id,
            analysis_id=analysis_id,
            finding_type=finding_type,
            severity=severity,
            title=f"{title}: {entity_label}",
            description=(
                f"Deterministic ranking by {cost_name}; unavailable values were excluded."
            ),
            object_type=object_type,
            provider_object_id=provider_object_id,
            dimensions=dimensions,
            evidence=evidence,
            confidence=confidence_for(metrics, configuration),
            missing_data=availability_notes(metrics),
            now=now,
        )

    def _budget_findings(
        self,
        *,
        run_id: str,
        analysis_id: str,
        snapshot: AdsSnapshot,
        current_rows: Sequence[InsightRow],
        configuration: MarketingAgentConfiguration,
        now: datetime,
    ) -> list[Finding]:
        results: list[Finding] = []
        grouped = group_rows(current_rows, key="ad_set_id")
        entities = {entity.provider_id: entity for entity in snapshot.ad_sets}
        for ad_set_id, rows in grouped.items():
            metrics = aggregate_metrics(rows)
            cost = cost_value(metrics, configuration)
            entity = entities.get(ad_set_id)
            if (
                entity is None
                or entity.daily_budget is None
                or entity.currency is None
                or cost is None
            ):
                continue
            is_paused = "PAUSED" in {entity.status.upper(), entity.effective_status.upper()}
            if (
                is_paused
                and qualifies(metrics, configuration)
                and cost <= configuration.acceptable_cpl_cpa
            ):
                finding_type = "efficient_paused"
                severity = FindingSeverity.INFO
                description = "A previously efficient ad set is paused and can be reconsidered."
            elif qualifies(metrics, configuration) and cost <= configuration.acceptable_cpl_cpa:
                finding_type = "budget_constrained_efficiency"
                severity = FindingSeverity.INFO
                description = (
                    "Efficient delivery has a finite daily budget and can be scaled safely."
                )
            elif metrics.spend.value is not None and cost > configuration.acceptable_cpl_cpa:
                finding_type = "budget_waste"
                severity = FindingSeverity.WARNING
                description = "Spend exceeds the configured efficiency target."
            else:
                continue
            results.append(
                self._finding(
                    run_id=run_id,
                    analysis_id=analysis_id,
                    finding_type=finding_type,
                    severity=severity,
                    title=f"Budget signal: {entity.name}",
                    description=description,
                    object_type="ad_set",
                    provider_object_id=ad_set_id,
                    dimensions={},
                    evidence=[
                        EvidenceMetric(
                            name="daily_budget",
                            current=MetricValue(
                                value=entity.daily_budget,
                                unit=entity.currency,
                                availability=DataAvailability.AVAILABLE,
                            ),
                        ),
                        EvidenceMetric(
                            name="objective_cost",
                            current=core_metric(
                                objective_cost(metrics, configuration)[1],
                                "currency/result",
                            ),
                        ),
                    ],
                    confidence=confidence_for(metrics, configuration),
                    missing_data=availability_notes(metrics),
                    now=now,
                ),
            )
        return results

    def _fatigue_and_anomaly_findings(
        self,
        *,
        run_id: str,
        analysis_id: str,
        current_rows: Sequence[InsightRow],
        baseline_rows: Sequence[InsightRow],
        configuration: MarketingAgentConfiguration,
        now: datetime,
    ) -> list[Finding]:
        findings: list[Finding] = []
        current_groups = group_rows(current_rows, key="creative_id")
        baseline_groups = group_rows(baseline_rows, key="creative_id")
        for creative_id, rows in current_groups.items():
            current = aggregate_metrics(rows)
            baseline = aggregate_metrics(baseline_groups.get(creative_id, []))
            ctr_drop = relative_drop(current.ctr, baseline.ctr)
            current_cost = objective_cost(current, configuration)[1]
            baseline_cost = objective_cost(baseline, configuration)[1]
            cost_growth = relative_growth(current_cost, baseline_cost)
            frequency = current.frequency.value
            fatigue = (
                frequency is not None
                and frequency >= configuration.maximum_frequency
                and ctr_drop is not None
                and ctr_drop >= configuration.ctr_decline_threshold
                and cost_growth is not None
                and cost_growth >= configuration.cpl_cpa_increase_threshold
            )
            if fatigue:
                findings.append(
                    self._finding(
                        run_id=run_id,
                        analysis_id=analysis_id,
                        finding_type="creative_fatigue",
                        severity=FindingSeverity.WARNING,
                        title=f"Creative fatigue: {rows[0].entity_name}",
                        description="Frequency rose while CTR fell and cost per result increased.",
                        object_type="creative",
                        provider_object_id=creative_id,
                        dimensions={},
                        evidence=[
                            EvidenceMetric(
                                name="frequency",
                                current=core_metric(current.frequency, "ratio"),
                                baseline=core_metric(baseline.frequency, "ratio"),
                            ),
                            EvidenceMetric(
                                name="ctr",
                                current=core_metric(current.ctr, "percent"),
                                baseline=core_metric(baseline.ctr, "percent"),
                            ),
                        ],
                        confidence=confidence_for(current, configuration),
                        missing_data=[],
                        now=now,
                    ),
                )
            anomaly_cutoff = (
                configuration.cpl_cpa_increase_threshold * configuration.anomaly_threshold
            )
            if cost_growth is not None and cost_growth >= anomaly_cutoff:
                findings.append(
                    self._finding(
                        run_id=run_id,
                        analysis_id=analysis_id,
                        finding_type="baseline_anomaly",
                        severity=FindingSeverity.WARNING,
                        title=f"Cost anomaly: {rows[0].entity_name}",
                        description=(
                            "Cost per result increased beyond the configured baseline threshold."
                        ),
                        object_type="creative",
                        provider_object_id=creative_id,
                        dimensions={},
                        evidence=[
                            EvidenceMetric(
                                name="cost_growth",
                                current=MetricValue(
                                    value=cost_growth,
                                    unit="ratio",
                                    availability=DataAvailability.AVAILABLE,
                                ),
                            ),
                        ],
                        confidence=confidence_for(current, configuration),
                        missing_data=[],
                        now=now,
                    ),
                )
        return findings

    def _recommendations(
        self,
        *,
        run_id: str,
        snapshot: AdsSnapshot,
        current_rows: Sequence[InsightRow],
        findings: Sequence[Finding],
        configuration: MarketingAgentConfiguration,
        now: datetime,
    ) -> list[Recommendation]:
        recommendations: list[Recommendation] = []
        entities = {
            entity.provider_id: entity
            for entity in [*snapshot.campaigns, *snapshot.ad_sets, *snapshot.ads]
        }
        by_creative = group_rows(current_rows, key="creative_id")
        by_audience = group_rows(current_rows, key="audience_id")
        for finding in findings:
            action = action_for_finding(finding.finding_type)
            if action is None or action not in configuration.allowed_action_types:
                continue
            target_id, object_type, parameters = recommendation_parameters(
                action=action,
                finding=finding,
                by_creative=by_creative,
                by_audience=by_audience,
                entities=entities,
                configuration=configuration,
                now=now,
            )
            if target_id is None or parameters is None:
                continue
            recommendations.append(
                Recommendation(
                    recommendation_id=self._ids.new(),
                    run_id=run_id,
                    finding_ids=[finding.finding_id],
                    object_type=object_type,
                    provider_object_id=target_id,
                    action_type=action,
                    parameters=parameters,
                    evidence=finding.evidence,
                    reasoning=finding.description,
                    confidence=finding.confidence,
                    expected_effect=expected_effect(action),
                    risks=action_risks(action),
                    missing_data=finding.missing_data,
                    expires_at=now + timedelta(hours=configuration.proposal_ttl_hours),
                    created_at=now,
                ),
            )
        if any(item.finding_type == "insufficient_data" for item in findings):
            recommendations.extend(
                self._observation_recommendations(run_id, findings, configuration, now),
            )
        return recommendations

    def _observation_recommendations(
        self,
        run_id: str,
        findings: Sequence[Finding],
        configuration: MarketingAgentConfiguration,
        now: datetime,
    ) -> list[Recommendation]:
        result: list[Recommendation] = []
        finding = next(item for item in findings if item.finding_type == "insufficient_data")
        if ActionType.OBSERVE in configuration.allowed_action_types:
            result.append(
                Recommendation(
                    recommendation_id=self._ids.new(),
                    run_id=run_id,
                    finding_ids=[finding.finding_id],
                    object_type="analysis",
                    provider_object_id="additional-observation",
                    action_type=ActionType.OBSERVE,
                    parameters=NoChangeActionParameters(
                        kind=ActionType.OBSERVE,
                        observation_until=now
                        + timedelta(days=configuration.comparison_period_days),
                    ),
                    evidence=finding.evidence,
                    reasoning="Wait for the missing provider breakdowns before changing delivery.",
                    confidence=Decimal("1"),
                    expected_effect="Increase decision confidence without changing spend.",
                    risks=[],
                    missing_data=finding.missing_data,
                    expires_at=now + timedelta(hours=configuration.proposal_ttl_hours),
                    created_at=now,
                ),
            )
        if ActionType.PROPOSE_TEST in configuration.allowed_action_types:
            result.append(
                Recommendation(
                    recommendation_id=self._ids.new(),
                    run_id=run_id,
                    finding_ids=[finding.finding_id],
                    object_type="test",
                    provider_object_id="breakdown-test",
                    action_type=ActionType.PROPOSE_TEST,
                    parameters=TestProposalParameters(
                        kind=ActionType.PROPOSE_TEST,
                        hypothesis="A controlled breakdown-compatible test can fill the data gap.",
                        test_type="measurement_observation",
                    ),
                    evidence=finding.evidence,
                    reasoning="Propose a test only; do not create provider entities automatically.",
                    confidence=Decimal("0.8"),
                    expected_effect="Collect comparable evidence for a later decision.",
                    risks=["The observation period delays optimization."],
                    missing_data=finding.missing_data,
                    expires_at=now + timedelta(hours=configuration.proposal_ttl_hours),
                    created_at=now,
                ),
            )
        return result

    def _finding(
        self,
        *,
        run_id: str,
        analysis_id: str,
        finding_type: str,
        severity: FindingSeverity,
        title: str,
        description: str,
        object_type: str | None,
        provider_object_id: str | None,
        dimensions: dict[str, str],
        evidence: list[EvidenceMetric],
        confidence: Decimal,
        missing_data: list[str],
        now: datetime,
    ) -> Finding:
        return Finding(
            finding_id=self._ids.new(),
            run_id=run_id,
            analysis_id=analysis_id,
            finding_type=finding_type,
            severity=severity,
            title=title,
            description=description,
            object_type=object_type,
            provider_object_id=provider_object_id,
            dimensions=dimensions,
            evidence=evidence,
            confidence=confidence,
            missing_data=missing_data,
            created_at=now,
        )


def aggregate_metrics(rows: Iterable[InsightRow]) -> PerformanceMetrics:
    materialized = list({row.row_id: row for row in rows}.values())
    base_rows = [row for row in materialized if row.dimensions.get("_query_scope") == "base"]
    if base_rows:
        materialized = base_rows
    if len({row.attribution_window for row in materialized}) > 1:
        return build_metrics(
            spend=None,
            impressions=None,
            reach=None,
            clicks=None,
            link_clicks=None,
            conversions=None,
            leads=None,
            revenue=None,
        )
    incomparable_currency = bool(materialized) and (
        any(row.currency is None for row in materialized) or len(currencies_for(materialized)) != 1
    )
    return build_metrics(
        spend=(
            None
            if incomparable_currency
            else sum_available(materialized, lambda item: item.metrics.spend)
        ),
        impressions=sum_available(materialized, lambda item: item.metrics.impressions),
        reach=(
            sum_available(materialized, lambda item: item.metrics.reach)
            if len(materialized) == 1
            else None
        ),
        clicks=sum_available(materialized, lambda item: item.metrics.clicks),
        link_clicks=sum_available(materialized, lambda item: item.metrics.link_clicks),
        conversions=sum_available(materialized, lambda item: item.metrics.conversions),
        leads=sum_available(materialized, lambda item: item.metrics.leads),
        revenue=(
            None
            if incomparable_currency
            else sum_available(materialized, lambda item: item.metrics.revenue)
        ),
    )


def sum_available(
    rows: Sequence[InsightRow],
    selector: Callable[[InsightRow], Metric],
) -> Decimal | None:
    values = [metric.value for row in rows if (metric := selector(row)).value is not None]
    return sum(values, Decimal("0")) if values else None


def group_rows(
    rows: Iterable[InsightRow],
    *,
    key: str,
    dimension: bool = False,
) -> dict[str, list[InsightRow]]:
    grouped: defaultdict[str, list[InsightRow]] = defaultdict(list)
    for row in rows:
        value = row.dimensions.get(key) if dimension else getattr(row, key, None)
        if isinstance(value, str) and value:
            grouped[value].append(row)
    return dict(grouped)


def metrics_for_analysis(metrics: PerformanceMetrics) -> dict[str, MetricValue]:
    units = {
        "spend": "currency",
        "impressions": "count",
        "reach": "count",
        "clicks": "count",
        "link_clicks": "count",
        "conversions": "count",
        "leads": "count",
        "revenue": "currency",
        "ctr": "percent",
        "cpc": "currency/click",
        "cpm": "currency/1000_impressions",
        "cpl": "currency/lead",
        "cpa": "currency/conversion",
        "roas": "ratio",
        "frequency": "ratio",
    }
    return {name: core_metric(getattr(metrics, name), unit) for name, unit in units.items()}


def core_metric(metric: Metric, unit: str) -> MetricValue:
    return MetricValue(
        value=metric.value,
        unit=unit,
        availability=metric.availability,
        reason=metric.reason,
    )


def objective_cost(
    metrics: PerformanceMetrics,
    configuration: MarketingAgentConfiguration,
) -> tuple[str, Metric]:
    if configuration.primary_objective is MarketingObjective.LEADS:
        return "cpl", metrics.cpl
    return "cpa", metrics.cpa


def cost_value(
    metrics: PerformanceMetrics,
    configuration: MarketingAgentConfiguration,
) -> Decimal | None:
    return objective_cost(metrics, configuration)[1].value


def metric_by_name(metrics: PerformanceMetrics, name: str) -> Metric:
    value = getattr(metrics, name)
    if not isinstance(value, Metric):
        raise TypeError(f"Unknown performance metric {name!r}")
    return value


def qualifies(
    metrics: PerformanceMetrics,
    configuration: MarketingAgentConfiguration,
) -> bool:
    spend = metrics.spend.value or Decimal("0")
    impressions = metrics.impressions.value or Decimal("0")
    clicks = metrics.clicks.value or Decimal("0")
    conversions = (
        metrics.leads.value
        if configuration.primary_objective is MarketingObjective.LEADS
        else metrics.conversions.value
    ) or Decimal("0")
    return (
        spend >= configuration.minimum_spend
        and impressions >= configuration.minimum_impressions
        and clicks >= configuration.minimum_clicks
        and conversions >= configuration.minimum_conversions
    )


def has_minimum_observation(
    metrics: PerformanceMetrics,
    configuration: MarketingAgentConfiguration,
) -> bool:
    return (
        (metrics.spend.value or Decimal("0")) >= configuration.minimum_spend
        and (metrics.impressions.value or Decimal("0")) >= configuration.minimum_impressions
        and (metrics.clicks.value or Decimal("0")) >= configuration.minimum_clicks
    )


def confidence_for(
    metrics: PerformanceMetrics,
    configuration: MarketingAgentConfiguration,
) -> Decimal:
    if qualifies(metrics, configuration):
        conversions = (
            metrics.leads.value
            if configuration.primary_objective is MarketingObjective.LEADS
            else metrics.conversions.value
        ) or Decimal("0")
        if conversions >= configuration.minimum_conversions * Decimal("3"):
            return Decimal("0.95")
        return Decimal("0.80")
    return Decimal("0.50")


def data_quality_score(snapshot: AdsSnapshot, rows: Sequence[InsightRow]) -> Decimal:
    if not rows:
        return Decimal("0")
    required = [
        "spend",
        "impressions",
        "clicks",
        "conversions",
        "ctr",
        "cpa",
    ]
    available_count = sum(
        1
        for name in required
        if any(
            getattr(row.metrics, name).availability is DataAvailability.AVAILABLE for row in rows
        )
    )
    metric_score = Decimal(available_count) / Decimal(len(required))
    diagnostics_score = Decimal("1") if snapshot.diagnostics else Decimal("0.8")
    score = metric_score * Decimal("0.8") + diagnostics_score * Decimal("0.2")
    if any(row.currency is None for row in rows) or len(currencies_for(rows)) > 1:
        score *= Decimal("0.5")
    return score.quantize(
        Decimal("0.01"),
    )


def currencies_for(rows: Iterable[InsightRow]) -> set[str]:
    return {row.currency.upper() for row in rows if row.currency is not None}


def period_coverage_notes(
    current_rows: Sequence[InsightRow],
    baseline_rows: Sequence[InsightRow],
    configuration: MarketingAgentConfiguration,
) -> list[str]:
    current_dates = {row.date_stop for row in current_rows}
    baseline_dates = {row.date_stop for row in baseline_rows}
    notes: list[str] = []
    if len(current_dates) < configuration.comparison_period_days:
        notes.append(
            "comparison period: "
            f"{len(current_dates)}/{configuration.comparison_period_days} days represented",
        )
    if len(baseline_dates) < configuration.baseline_period_days:
        notes.append(
            "baseline period: "
            f"{len(baseline_dates)}/{configuration.baseline_period_days} days represented",
        )
    return notes


def availability_notes(metrics: PerformanceMetrics) -> list[str]:
    return [
        f"{name}: {metric.reason or 'unavailable'}"
        for name in ["ctr", "cpc", "cpm", "cpl", "cpa", "roas", "frequency"]
        if (metric := metric_by_name(metrics, name)).availability is DataAvailability.UNAVAILABLE
    ]


def relative_drop(current: Metric, baseline: Metric) -> Decimal | None:
    if current.value is None or baseline.value is None or baseline.value == 0:
        return None
    return (baseline.value - current.value) / baseline.value


def relative_growth(current: Metric, baseline: Metric) -> Decimal | None:
    return relative_growth_values(current.value, baseline.value)


def relative_growth_values(current: Decimal | None, baseline: Decimal | None) -> Decimal | None:
    if current is None or baseline is None or baseline == 0:
        return None
    return (current - baseline) / baseline


def action_for_finding(finding_type: str) -> ActionType | None:
    return {
        "best_creative": ActionType.MAINTAIN,
        "budget_constrained_efficiency": ActionType.INCREASE_BUDGET,
        "budget_waste": ActionType.DECREASE_BUDGET,
        "efficient_paused": ActionType.RESUME,
        "weak_creative": ActionType.PAUSE,
        "creative_fatigue": ActionType.PAUSE,
        "cheap_audience": ActionType.SCALE_AUDIENCE,
        "expensive_audience": ActionType.DISABLE_AUDIENCE,
    }.get(finding_type)


def recommendation_parameters(
    *,
    action: ActionType,
    finding: Finding,
    by_creative: dict[str, list[InsightRow]],
    by_audience: dict[str, list[InsightRow]],
    entities: dict[str, AdEntity],
    configuration: MarketingAgentConfiguration,
    now: datetime,
) -> tuple[
    str | None,
    str,
    BudgetActionParameters
    | StatusActionParameters
    | AudienceActionParameters
    | NoChangeActionParameters
    | TestProposalParameters
    | None,
]:
    del now
    target_id = finding.provider_object_id
    if target_id is None:
        return None, finding.object_type or "unknown", None
    if action in {ActionType.INCREASE_BUDGET, ActionType.DECREASE_BUDGET}:
        entity = entities.get(target_id)
        if entity is None or entity.daily_budget is None or entity.currency is None:
            return None, "ad_set", None
        if action is ActionType.INCREASE_BUDGET:
            proposed = min(
                entity.daily_budget * configuration.maximum_budget_increase_factor,
                entity.daily_budget + configuration.maximum_absolute_daily_budget_change,
            )
        else:
            proposed = max(
                Decimal("0.01"),
                entity.daily_budget * (Decimal("1") - configuration.maximum_budget_decrease),
                entity.daily_budget - configuration.maximum_absolute_daily_budget_change,
            )
        return (
            target_id,
            "ad_set",
            BudgetActionParameters(
                kind=action,
                currency=entity.currency,
                current_daily_budget=entity.daily_budget,
                proposed_daily_budget=proposed,
            ),
        )
    if action is ActionType.PAUSE:
        if finding.object_type == "creative":
            creative_rows = by_creative.get(target_id, [])
            target_id = creative_rows[0].ad_id if creative_rows else None
        if target_id is None:
            return None, "ad", None
        entity = entities.get(target_id)
        current_status = entity.status if entity is not None else "ACTIVE"
        return (
            target_id,
            "ad",
            StatusActionParameters(
                kind=ActionType.PAUSE,
                current_status=current_status,
                proposed_status="PAUSED",
            ),
        )
    if action is ActionType.RESUME:
        entity = entities.get(target_id)
        if entity is None:
            return None, finding.object_type or "ad_set", None
        return (
            target_id,
            finding.object_type or "ad_set",
            StatusActionParameters(
                kind=ActionType.RESUME,
                current_status=entity.status,
                proposed_status="ACTIVE",
            ),
        )
    if action in {ActionType.SCALE_AUDIENCE, ActionType.DISABLE_AUDIENCE}:
        audience_id = target_id
        audience_rows = by_audience.get(audience_id, [])
        target_id = audience_rows[0].ad_set_id if audience_rows else None
        if target_id is None:
            return None, "ad_set", None
        entity = entities.get(target_id)
        if entity is None:
            return None, "ad_set", None
        proposed_status = "ACTIVE" if action is ActionType.SCALE_AUDIENCE else "PAUSED"
        budget_change: BudgetActionParameters | None = None
        if (
            action is ActionType.SCALE_AUDIENCE
            and entity.daily_budget is not None
            and entity.currency is not None
        ):
            proposed_budget = min(
                entity.daily_budget * configuration.maximum_budget_increase_factor,
                entity.daily_budget + configuration.maximum_absolute_daily_budget_change,
            )
            budget_change = BudgetActionParameters(
                kind=ActionType.INCREASE_BUDGET,
                currency=entity.currency,
                current_daily_budget=entity.daily_budget,
                proposed_daily_budget=proposed_budget,
            )
        return (
            target_id,
            "ad_set",
            AudienceActionParameters(
                kind=action,
                audience_id=audience_id,
                current_status=entity.status,
                proposed_status=proposed_status,
                budget_change=budget_change,
            ),
        )
    if action is ActionType.MAINTAIN:
        return (
            target_id,
            finding.object_type or "unknown",
            NoChangeActionParameters(kind=ActionType.MAINTAIN),
        )
    return None, finding.object_type or "unknown", None


def expected_effect(action: ActionType) -> str:
    return {
        ActionType.INCREASE_BUDGET: "Capture more efficient conversions within policy limits.",
        ActionType.DECREASE_BUDGET: "Reduce inefficient spend while preserving observation data.",
        ActionType.PAUSE: "Stop further spend on a weak or fatigued object.",
        ActionType.RESUME: "Restore delivery for an efficient previously paused object.",
        ActionType.SCALE_AUDIENCE: "Increase reach in a low-cost audience.",
        ActionType.DISABLE_AUDIENCE: "Stop spend in an expensive audience.",
        ActionType.MAINTAIN: "Keep the current state unchanged.",
        ActionType.OBSERVE: "Gather additional evidence without changing spend.",
        ActionType.PROPOSE_TEST: "Define a controlled test for later approval and implementation.",
    }[action]


def action_risks(action: ActionType) -> list[str]:
    if action in {ActionType.INCREASE_BUDGET, ActionType.SCALE_AUDIENCE}:
        return ["Efficiency can degrade after scaling.", "Additional spend is committed."]
    if action in {ActionType.PAUSE, ActionType.DISABLE_AUDIENCE}:
        return ["Delivery and conversion volume may decrease."]
    if action is ActionType.DECREASE_BUDGET:
        return ["Reduced budget can constrain a recovering campaign."]
    return []
