import asyncio
import hashlib
import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast

from pydantic import JsonValue

from app.mana_operation_ai.application.action_lifecycle import ActionLifecycleService
from app.mana_operation_ai.application.ports import (
    AttributionPort,
    BillingReadPort,
    Clock,
    ExperimentPlatform,
    IdGenerator,
    OperationRepository,
    ProductAnalyticsPort,
)
from app.mana_operation_ai.application.scheduling import next_cron_occurrence
from app.mana_operation_ai.domain.enums import (
    ActionStatus,
    AgentRunStage,
    AgentRunStatus,
    AuditEventType,
    CapabilityRisk,
    DataAvailability,
    FindingSeverity,
    GrowthActionType,
    OutcomeEvaluationStatus,
    TriggerType,
    UserRole,
)
from app.mana_operation_ai.domain.growth import (
    AttributionFacts,
    BillingFunnelFacts,
    GrowthFunnelConfiguration,
    GrowthFunnelSnapshot,
    ProductAnalyticsFacts,
)
from app.mana_operation_ai.domain.models import (
    AgentConfiguration,
    AgentReport,
    AgentRun,
    AgentRunResult,
    AgentSchedule,
    Analysis,
    AuditEvent,
    CapabilityDefinition,
    CreateExperimentActionParameters,
    DataSnapshot,
    EvidenceMetric,
    EvidenceRef,
    Finding,
    IntegrationHealth,
    MetricValue,
    OutcomeEvaluation,
    Recommendation,
)
from app.mana_operation_ai.domain.state_machine import RUN_TRANSITIONS, require_transition

from .constants import FUNNEL_CAPABILITY_KEY, GROWTH_AGENT_ID


class GrowthFunnelCapabilityHandler:
    def __init__(
        self,
        *,
        product_analytics: ProductAnalyticsPort,
        billing: BillingReadPort,
        attribution: AttributionPort,
        experiments: ExperimentPlatform,
        actions: ActionLifecycleService,
        repository: OperationRepository,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._product_analytics = product_analytics
        self._billing = billing
        self._attribution = attribution
        self._experiments = experiments
        self._actions = actions
        self._repository = repository
        self._clock = clock
        self._ids = ids
        self._definition = CapabilityDefinition(
            key=FUNNEL_CAPABILITY_KEY,
            agent_id=GROWTH_AGENT_ID,
            description=(
                "Calculates authoritative acquisition-to-paid funnel metrics and proposes "
                "bounded sandbox experiments when a stage materially underperforms."
            ),
            risk=CapabilityRisk.FINANCIAL,
            minimum_role=UserRole.OPERATOR,
            input_schema=cast(
                dict[str, JsonValue],
                GrowthFunnelConfiguration.model_json_schema(),
            ),
            output_schema=cast(dict[str, JsonValue], AgentRunResult.model_json_schema()),
            required_integrations=[
                "product_analytics",
                "billing",
                "attribution",
                experiments.provider_name,
            ],
            supported_triggers={TriggerType.USER, TriggerType.SCHEDULE},
        )

    @property
    def definition(self) -> CapabilityDefinition:
        return self._definition

    @property
    def default_configuration(self) -> dict[str, JsonValue]:
        return cast(
            dict[str, JsonValue],
            GrowthFunnelConfiguration().model_dump(mode="json"),
        )

    def default_schedules(self, agent_id: str) -> list[AgentSchedule]:
        configuration = GrowthFunnelConfiguration()
        return [self._schedule(agent_id, configuration, None)]

    def schedules_for_configuration(
        self,
        *,
        agent_id: str,
        values: dict[str, JsonValue],
        existing: Sequence[AgentSchedule],
    ) -> list[AgentSchedule]:
        configuration = GrowthFunnelConfiguration.model_validate(values)
        previous = next(
            (item for item in existing if item.schedule_id == "growth-funnel-analysis"),
            None,
        )
        return [self._schedule(agent_id, configuration, previous)]

    def validate_configuration(self, values: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return cast(
            dict[str, JsonValue],
            GrowthFunnelConfiguration.model_validate(values).model_dump(mode="json"),
        )

    async def health(self) -> list[IntegrationHealth]:
        return [await self._experiments.health()]

    async def execute(
        self,
        *,
        run: AgentRun,
        job_type: str,
        configuration: AgentConfiguration,
    ) -> AgentRunResult:
        if job_type != "analysis":
            raise ValueError(f"Unsupported funnel job type {job_type!r}")
        typed_configuration = GrowthFunnelConfiguration.model_validate(configuration.values)
        try:
            run = await self._transition(run, AgentRunStatus.COLLECTING, AgentRunStage.COLLECT)
            period_end = self._clock.now()
            period_start = period_end - timedelta(days=typed_configuration.lookback_days)
            product, billing, attribution = await asyncio.gather(
                self._product_analytics.collect_funnel(
                    period_start=period_start,
                    period_end=period_end,
                ),
                self._billing.collect_funnel(
                    period_start=period_start,
                    period_end=period_end,
                ),
                self._attribution.collect_funnel(
                    period_start=period_start,
                    period_end=period_end,
                ),
            )
            run = await self._transition(
                run,
                AgentRunStatus.NORMALIZING,
                AgentRunStage.NORMALIZE,
            )
            normalized = _normalize(product, billing, attribution, self._clock.now())
            snapshot = self._snapshot(run, normalized)
            await self._repository.save_snapshot(snapshot)

            run = await self._transition(run, AgentRunStatus.ANALYZING, AgentRunStage.ANALYZE)
            analysis, finding = self._analyze(
                run=run,
                snapshot=snapshot,
                normalized=normalized,
                configuration=typed_configuration,
            )
            await self._repository.save_analysis(analysis)
            findings = [finding] if finding is not None else []
            await self._repository.save_findings(findings)

            run = await self._transition(run, AgentRunStatus.PROPOSING, AgentRunStage.PROPOSE)
            recommendations = (
                [
                    self._experiment_recommendation(
                        run=run,
                        finding=finding,
                        configuration=typed_configuration,
                    ),
                ]
                if finding is not None
                else []
            )
            await self._repository.save_recommendations(recommendations)
            proposals = []
            run = await self._transition(
                run,
                AgentRunStatus.POLICY_CHECK,
                AgentRunStage.POLICY_CHECK,
            )
            if recommendations and typed_configuration.experiment_mode == "sandbox":
                creation = await self._actions.create_proposal(
                    agent_id=run.agent_id,
                    provider_name=self._experiments.provider_name,
                    run_id=run.run_id,
                    correlation_id=run.correlation_id,
                    recommendation=recommendations[0],
                    configuration=cast(
                        dict[str, JsonValue],
                        typed_configuration.model_dump(mode="json"),
                    ),
                    configuration_version=configuration.version,
                    requested_by=run.initiated_by,
                )
                if creation is not None:
                    proposals.append(creation.proposal)
                    if creation.approval is not None:
                        run = await self._transition(
                            run,
                            AgentRunStatus.WAITING_APPROVAL,
                            AgentRunStage.APPROVAL,
                        )
                        return AgentRunResult(
                            run_id=run.run_id,
                            status=run.status,
                            snapshot_ids=[snapshot.snapshot_id],
                            finding_ids=[item.finding_id for item in findings],
                            recommendation_ids=[item.recommendation_id for item in recommendations],
                            action_proposal_ids=[creation.proposal.proposal_id],
                        )
            return await self._finish(
                run=run,
                snapshot=normalized,
                findings=findings,
                recommendations=recommendations,
                action_proposal_ids=[item.proposal_id for item in proposals],
            )
        except Exception as exc:
            if run.status is not AgentRunStatus.FAILED:
                require_transition(run.status, AgentRunStatus.FAILED, RUN_TRANSITIONS)
                failed = run.model_copy(
                    update={
                        "status": AgentRunStatus.FAILED,
                        "updated_at": self._clock.now(),
                        "completed_at": self._clock.now(),
                        "error_code": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
                await self._repository.update_run(failed)
            raise

    async def finalize_after_actions(self, run_id: str) -> AgentRunResult:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise LookupError(f"Run {run_id!r} was not found")
        if run.status is not AgentRunStatus.WAITING_APPROVAL:
            return AgentRunResult(run_id=run.run_id, status=run.status)
        proposals, _ = await self._repository.list_proposals(run_id=run_id, limit=100)
        if any(
            item.status
            in {ActionStatus.AWAITING_APPROVAL, ActionStatus.APPROVED, ActionStatus.EXECUTING}
            for item in proposals
        ):
            return AgentRunResult(
                run_id=run.run_id,
                status=run.status,
                action_proposal_ids=[item.proposal_id for item in proposals],
            )
        snapshots = await self._repository.list_snapshots(run_id)
        if not snapshots:
            raise RuntimeError("The funnel run has no persisted snapshot")
        snapshot = GrowthFunnelSnapshot.model_validate(snapshots[-1].payload)
        findings, _ = await self._repository.list_findings(run_id=run_id, limit=100)
        recommendations, _ = await self._repository.list_recommendations(run_id=run_id, limit=100)
        executions = []
        for proposal in proposals:
            execution = await self._repository.get_execution_for_proposal(proposal.proposal_id)
            if execution is not None:
                executions.append(execution)
            if execution is None or proposal.status is not ActionStatus.SUCCEEDED:
                continue
            existing, _ = await self._repository.list_outcome_evaluations(
                proposal_id=proposal.proposal_id,
                limit=1,
            )
            if existing:
                continue
            parameters = proposal.parameters
            if not isinstance(parameters, CreateExperimentActionParameters):
                continue
            await self._repository.save_outcome_evaluation(
                OutcomeEvaluation(
                    evaluation_id=self._ids.new(),
                    run_id=run.run_id,
                    proposal_id=proposal.proposal_id,
                    agent_id=run.agent_id,
                    capability_key=run.capability_key,
                    metric_name=parameters.primary_metric,
                    baseline_value=(findings[0].evidence[0].current.value if findings else None),
                    target_value=None,
                    status=OutcomeEvaluationStatus.PENDING,
                    attribution_limitations=[
                        "Provider-state verification does not prove business impact.",
                        "The experiment must complete before a causal outcome is measured.",
                    ],
                    measurement_due_at=self._clock.now() + timedelta(days=parameters.duration_days),
                    evaluated_at=self._clock.now(),
                ),
            )
        if executions:
            run = await self._transition(run, AgentRunStatus.EXECUTING, AgentRunStage.EXECUTE)
        if any(
            item.status in {ActionStatus.SUCCEEDED, ActionStatus.PARTIALLY_APPLIED}
            for item in proposals
        ):
            run = await self._transition(run, AgentRunStatus.VERIFYING, AgentRunStage.VERIFY)
        return await self._finish(
            run=run,
            snapshot=snapshot,
            findings=findings,
            recommendations=recommendations,
            action_proposal_ids=[item.proposal_id for item in proposals],
        )

    async def _finish(
        self,
        *,
        run: AgentRun,
        snapshot: GrowthFunnelSnapshot,
        findings: list[Finding],
        recommendations: list[Recommendation],
        action_proposal_ids: list[str],
    ) -> AgentRunResult:
        run = await self._transition(run, AgentRunStatus.REPORTING, AgentRunStage.REPORT)
        report = AgentReport(
            report_id=self._ids.new(),
            agent_id=run.agent_id,
            capability_key=run.capability_key,
            run_id=run.run_id,
            report_type="funnel_analysis",
            period_start=snapshot.period_start,
            period_end=snapshot.period_end,
            structured={
                "stage_counts": {
                    "visitors": snapshot.visitors,
                    "signups": snapshot.signups,
                    "activated_users": snapshot.activated_users,
                    "trials_started": snapshot.trials_started,
                    "paid_subscriptions": snapshot.paid_subscriptions,
                },
                "completeness": str(snapshot.completeness),
                "finding_ids": [item.finding_id for item in findings],
                "recommendation_ids": [item.recommendation_id for item in recommendations],
            },
            human_readable=(
                f"Funnel analyzed from {snapshot.visitors} visitors to "
                f"{snapshot.paid_subscriptions} paid subscriptions. "
                f"Generated {len(findings)} deterministic finding(s)."
            ),
            data_quality_notes=snapshot.limitations,
            created_at=self._clock.now(),
        )
        await self._repository.save_report(report)
        run = await self._transition(run, AgentRunStatus.COMPLETED, AgentRunStage.REPORT)
        return AgentRunResult(
            run_id=run.run_id,
            status=run.status,
            snapshot_ids=[
                item.snapshot_id for item in await self._repository.list_snapshots(run.run_id)
            ],
            finding_ids=[item.finding_id for item in findings],
            recommendation_ids=[item.recommendation_id for item in recommendations],
            action_proposal_ids=action_proposal_ids,
            report_id=report.report_id,
            completed_at=run.completed_at,
        )

    def _analyze(
        self,
        *,
        run: AgentRun,
        snapshot: DataSnapshot,
        normalized: GrowthFunnelSnapshot,
        configuration: GrowthFunnelConfiguration,
    ) -> tuple[Analysis, Finding | None]:
        stage_pairs = {
            "visitor_to_signup": (normalized.visitors, normalized.signups),
            "signup_to_activation": (normalized.signups, normalized.activated_users),
            "activation_to_trial": (normalized.activated_users, normalized.trials_started),
            "trial_to_paid": (normalized.trials_started, normalized.paid_subscriptions),
        }
        metrics = {
            key: _ratio_metric(numerator=target, denominator=source)
            for key, (source, target) in stage_pairs.items()
        }
        analysis = Analysis(
            analysis_id=self._ids.new(),
            run_id=run.run_id,
            snapshot_id=snapshot.snapshot_id,
            calculated_at=self._clock.now(),
            metrics=metrics,
            baseline_metrics={},
            data_quality_score=normalized.completeness,
            notes=[
                "All funnel ratios are deterministic decimal calculations over normalized facts.",
                *normalized.limitations,
            ],
        )
        available = {
            key: metric.value for key, metric in metrics.items() if metric.value is not None
        }
        if not available or normalized.completeness < configuration.minimum_completeness:
            return analysis, None
        weakest_stage, weakest_value = min(available.items(), key=lambda item: item[1])
        if weakest_value >= configuration.minimum_stage_conversion:
            return analysis, None
        evidence = EvidenceMetric(
            name=weakest_stage,
            current=metrics[weakest_stage],
        )
        finding = Finding(
            finding_id=self._ids.new(),
            run_id=run.run_id,
            analysis_id=analysis.analysis_id,
            finding_type="funnel_stage_underperformance",
            severity=FindingSeverity.WARNING,
            title=f"Weak conversion at {weakest_stage}",
            description=(
                f"The deterministic conversion rate {weakest_value:.4f} is below the configured "
                f"minimum {configuration.minimum_stage_conversion:.4f}."
            ),
            object_type="funnel_stage",
            provider_object_id=weakest_stage,
            evidence=[evidence],
            confidence=normalized.completeness,
            source_snapshot_id=snapshot.snapshot_id,
            period_start=normalized.period_start,
            period_end=normalized.period_end,
            attribution_identity="normalized_account_cohort",
            deterministic_calculation="target_stage_count / source_stage_count",
            completeness=normalized.completeness,
            limitations=normalized.limitations,
            created_at=self._clock.now(),
        )
        return analysis, finding

    def _experiment_recommendation(
        self,
        *,
        run: AgentRun,
        finding: Finding,
        configuration: GrowthFunnelConfiguration,
    ) -> Recommendation:
        metric = finding.evidence[0]
        experiment_key = f"improve-{finding.provider_object_id}".replace("_", "-")
        return Recommendation(
            recommendation_id=self._ids.new(),
            run_id=run.run_id,
            finding_ids=[finding.finding_id],
            object_type="experiment",
            provider_object_id=experiment_key,
            capability_key=FUNNEL_CAPABILITY_KEY,
            action_family="growth_experiment",
            action_type=GrowthActionType.CREATE_EXPERIMENT,
            parameters=CreateExperimentActionParameters(
                kind=GrowthActionType.CREATE_EXPERIMENT,
                experiment_key=experiment_key,
                hypothesis=(
                    f"A bounded UX treatment will improve {finding.provider_object_id} without "
                    "reducing downstream paid conversion."
                ),
                primary_metric=str(finding.provider_object_id),
                audience_segment="eligible_new_accounts",
                allocation_percent=configuration.experiment_allocation_percent,
                duration_days=configuration.experiment_duration_days,
            ),
            evidence=[metric],
            reasoning=(
                "The lowest deterministic funnel ratio is below the configured threshold; a "
                "small sandbox experiment is safer than publishing an offer directly."
            ),
            confidence=finding.confidence,
            expected_effect=f"Increase {finding.provider_object_id} conversion.",
            risks=["Selection bias", "Short measurement window", "Downstream metric regression"],
            missing_data=[],
            expires_at=self._clock.now() + timedelta(hours=configuration.proposal_ttl_hours),
            created_at=self._clock.now(),
        )

    async def _transition(
        self,
        run: AgentRun,
        target: AgentRunStatus,
        stage: AgentRunStage,
    ) -> AgentRun:
        require_transition(run.status, target, RUN_TRANSITIONS)
        now = self._clock.now()
        updated = run.model_copy(
            update={
                "status": target,
                "current_stage": stage,
                "updated_at": now,
                "completed_at": now if target is AgentRunStatus.COMPLETED else None,
            },
        )
        await self._repository.update_run(updated)
        await self._repository.save_audit_event(
            AuditEvent(
                event_id=self._ids.new(),
                correlation_id=run.correlation_id,
                agent_id=run.agent_id,
                capability_key=run.capability_key,
                run_id=run.run_id,
                event_type=AuditEventType.RUN_STAGE_CHANGED,
                actor_id=run.initiated_by,
                actor_role=UserRole.OPERATOR,
                occurred_at=now,
                summary=f"Run moved to {target.value}",
                details={"stage": stage.value},
            ),
        )
        return updated

    def _snapshot(self, run: AgentRun, snapshot: GrowthFunnelSnapshot) -> DataSnapshot:
        payload = cast(dict[str, JsonValue], snapshot.model_dump(mode="json"))
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return DataSnapshot(
            snapshot_id=self._ids.new(),
            run_id=run.run_id,
            agent_id=run.agent_id,
            capability_key=run.capability_key,
            provider="normalized_growth_funnel",
            schema_version=snapshot.schema_version,
            period_start=snapshot.period_start,
            period_end=snapshot.period_end,
            collected_at=snapshot.collected_at,
            checksum=hashlib.sha256(serialized.encode()).hexdigest(),
            provider_request_ids=[item.source for item in snapshot.evidence_refs],
            completeness=snapshot.completeness,
            evidence_refs=snapshot.evidence_refs,
            payload=payload,
        )

    def _schedule(
        self,
        agent_id: str,
        configuration: GrowthFunnelConfiguration,
        previous: AgentSchedule | None,
    ) -> AgentSchedule:
        return AgentSchedule(
            schedule_id="growth-funnel-analysis",
            agent_id=agent_id,
            capability_key=FUNNEL_CAPABILITY_KEY,
            job_type="analysis",
            cron_expression=configuration.schedule,
            timezone=configuration.timezone,
            enabled=previous.enabled if previous is not None else True,
            next_run_at=next_cron_occurrence(
                configuration.schedule,
                configuration.timezone,
                self._clock.now(),
            ),
            last_run_at=previous.last_run_at if previous is not None else None,
        )


def _normalize(
    product: ProductAnalyticsFacts,
    billing: BillingFunnelFacts,
    attribution: AttributionFacts,
    collected_at: datetime,
) -> GrowthFunnelSnapshot:
    period_start = max(product.period_start, billing.period_start, attribution.period_start)
    period_end = min(product.period_end, billing.period_end, attribution.period_end)
    activated_users = min(product.activated_users, billing.activated_users)
    limitations: list[str] = []
    if product.activated_users != billing.activated_users:
        limitations.append(
            "Product and billing activation cohorts differ; the smaller aligned cohort was used.",
        )
    attributed_visitors = sum(item.visitors for item in attribution.channels)
    if attributed_visitors != product.visitors:
        limitations.append(
            "Channel attribution is incomplete and is not used as the authoritative visitor total.",
        )
    completeness = min(product.completeness, billing.completeness, attribution.completeness)
    evidence_refs = [_evidence_ref(item, collected_at) for item in (product, billing, attribution)]
    return GrowthFunnelSnapshot(
        period_start=period_start,
        period_end=period_end,
        collected_at=collected_at,
        visitors=product.visitors,
        signups=product.signups,
        activated_users=activated_users,
        trials_started=min(billing.trials_started, activated_users),
        paid_subscriptions=min(billing.paid_subscriptions, billing.trials_started),
        recognized_revenue=billing.recognized_revenue,
        currency=billing.currency,
        channels=attribution.channels,
        completeness=completeness,
        evidence_refs=evidence_refs,
        limitations=limitations,
    )


def _evidence_ref(
    facts: ProductAnalyticsFacts | BillingFunnelFacts | AttributionFacts,
    collected_at: datetime,
) -> EvidenceRef:
    payload = facts.model_dump(mode="json")
    checksum = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
    ).hexdigest()
    return EvidenceRef(
        source=facts.source,
        subject_scope="aggregated_account_cohort",
        period_start=facts.period_start,
        period_end=facts.period_end,
        collected_at=facts.collected_at,
        freshness_seconds=max(int((collected_at - facts.collected_at).total_seconds()), 0),
        completeness=facts.completeness,
        checksum=checksum,
        privacy_classification="user_behavioral_financial_high",
    )


def _ratio_metric(*, numerator: int, denominator: int) -> MetricValue:
    if denominator == 0:
        return MetricValue(
            value=None,
            unit="ratio",
            availability=DataAvailability.UNAVAILABLE,
            reason="The source stage has no observations.",
        )
    return MetricValue(
        value=Decimal(numerator) / Decimal(denominator),
        unit="ratio",
        availability=DataAvailability.AVAILABLE,
    )
