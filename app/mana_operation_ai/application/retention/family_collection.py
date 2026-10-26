"""Manual saved-aggregate analysis inside the existing Retention owner."""

import hashlib
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Protocol, cast

from pydantic import JsonValue

from app.mana_operation_ai.application.ports import Clock, IdGenerator, OperationRepository
from app.mana_operation_ai.application.retention.constants import RETENTION_AGENT_ID
from app.mana_operation_ai.domain.enums import (
    AgentRunStage,
    AgentRunStatus,
    AuditEventType,
    CapabilityRisk,
    TriggerType,
    UserRole,
)
from app.mana_operation_ai.domain.family_collection import (
    SavedCollectionConfiguration,
    SavedCollectionFacts,
)
from app.mana_operation_ai.domain.models import (
    AgentConfiguration,
    AgentReport,
    AgentRun,
    AgentRunResult,
    AgentSchedule,
    AuditEvent,
    CapabilityDefinition,
    DataSnapshot,
    EvidenceRef,
    IntegrationHealth,
)
from app.mana_operation_ai.domain.state_machine import RUN_TRANSITIONS, require_transition

COLLECTION_CAPABILITY = "retention.family_collection.analyze"
_LIMITATIONS = [
    "Saved MANA collection coverage, not current sensor measurements or parent "
    "behavioral analytics.",
    "Parent inventory is paginated, not a point-in-time population; population "
    "coverage is unproven.",
    "Source targets and cache hits are not unique active users, sessions, churn "
    "or paid conversions.",
    "Low battery records do not establish child danger; no GPS, family IDs or "
    "chat text is included.",
    "Collection, provider-check and observation dates differ; undated measurements remain undated.",
    "No new provider read, inference, contact, payment, source refresh or schedule is performed.",
]


class SavedCollectionSource(Protocol):
    async def collect(self, now: datetime, *, maximum_age_seconds: int) -> SavedCollectionFacts: ...


class SavedCollectionCapabilityHandler:
    def __init__(
        self,
        source: SavedCollectionSource,
        *,
        repository: OperationRepository,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._source, self._repository, self._clock, self._ids = source, repository, clock, ids
        self._definition = CapabilityDefinition(
            key=COLLECTION_CAPABILITY,
            agent_id=RETENTION_AGENT_ID,
            description=(
                "Summarizes an existing minimized MANA collection publication "
                "without rereading providers."
            ),
            risk=CapabilityRisk.READ,
            minimum_role=UserRole.OPERATOR,
            input_schema=cast(
                dict[str, JsonValue], SavedCollectionConfiguration.model_json_schema()
            ),
            output_schema=cast(dict[str, JsonValue], AgentRunResult.model_json_schema()),
            required_integrations=[],
            supported_triggers={TriggerType.USER, TriggerType.API, TriggerType.ORCHESTRATOR},
        )

    @property
    def definition(self) -> CapabilityDefinition:
        return self._definition

    @property
    def default_configuration(self) -> dict[str, JsonValue]:
        return self.validate_configuration({})

    def default_schedules(self, agent_id: str) -> list[AgentSchedule]:
        return []

    def schedules_for_configuration(
        self, *, agent_id: str, values: dict[str, JsonValue], existing: Sequence[AgentSchedule]
    ) -> list[AgentSchedule]:
        self.validate_configuration(values)
        return []

    def validate_configuration(self, values: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return cast(
            dict[str, JsonValue], SavedCollectionConfiguration.model_validate(values).model_dump()
        )

    async def health(self) -> list[IntegrationHealth]:
        # Startup/health/views do not open the private source file.
        return []

    async def execute(
        self, *, run: AgentRun, job_type: str, configuration: AgentConfiguration
    ) -> AgentRunResult:
        if (
            job_type != "analysis"
            or run.trigger not in self.definition.supported_triggers
            or run.agent_id != RETENTION_AGENT_ID
            or configuration.agent_id != RETENTION_AGENT_ID
            or run.capability_key != COLLECTION_CAPABILITY
            or configuration.capability_key != COLLECTION_CAPABILITY
        ):
            raise ValueError("Saved collection analysis is manual only")
        settings = SavedCollectionConfiguration.model_validate(configuration.values)
        run = await self._transition(run, AgentRunStatus.COLLECTING, AgentRunStage.COLLECT)
        facts = await self._source.collect(
            self._clock.now(), maximum_age_seconds=settings.maximum_age_seconds
        )
        for status, stage in (
            (AgentRunStatus.NORMALIZING, AgentRunStage.NORMALIZE),
            (AgentRunStatus.ANALYZING, AgentRunStage.ANALYZE),
            (AgentRunStatus.PROPOSING, AgentRunStage.PROPOSE),
            (AgentRunStatus.POLICY_CHECK, AgentRunStage.POLICY_CHECK),
            (AgentRunStatus.REPORTING, AgentRunStage.REPORT),
        ):
            run = await self._transition(run, status, stage)
        payload = cast(dict[str, JsonValue], facts.model_dump(mode="json"))
        checksum = hashlib.sha256(
            facts.model_dump_json(exclude={"inspected_at"}).encode()
        ).hexdigest()
        evidence = EvidenceRef(
            source="saved_mana_family_collection",
            subject_scope="MANA saved connected-child collection coverage; not parent activity",
            period_start=facts.scheduled_at,
            period_end=facts.published_at,
            collected_at=facts.published_at,
            freshness_seconds=facts.age_seconds(self._clock.now()),
            completeness=Decimal(0),
            checksum=checksum,
            privacy_classification="aggregate_no_family_identifiers",
        )
        snapshot = DataSnapshot(
            snapshot_id=self._ids.new(),
            run_id=run.run_id,
            agent_id=RETENTION_AGENT_ID,
            capability_key=COLLECTION_CAPABILITY,
            provider="saved_mana_family_collection",
            schema_version=facts.schema_version,
            period_start=facts.scheduled_at,
            period_end=facts.published_at,
            collected_at=facts.published_at,
            checksum=checksum,
            provider_request_ids=[],
            completeness=Decimal(0),
            evidence_refs=[evidence],
            payload=payload,
        )
        await self._repository.save_snapshot(snapshot)
        rows = [
            f"{item.source}: {item.completed}/{item.target_reads} target attempts completed, "
            f"{item.cache_hits} cache hits, {item.failed} failed, {item.unknown} unknown, "
            f"{item.skipped} skipped, {item.unavailable} unavailable."
            for item in facts.counts
        ]
        report = AgentReport(
            report_id=self._ids.new(),
            run_id=run.run_id,
            agent_id=RETENTION_AGENT_ID,
            capability_key=COLLECTION_CAPABILITY,
            report_type="saved_mana_family_collection",
            period_start=facts.scheduled_at,
            period_end=facts.published_at,
            structured={**payload, "evidence_refs": [evidence.model_dump(mode="json")]},
            human_readable=(
                f"Saved MANA collection {facts.scheduled_at.isoformat()}: {facts.status}. "
                f"Inventory saw {facts.parents_seen} parent records; {facts.targets} source "
                "target attempts. Population coverage is unproven.\n" + "\n".join(rows)
            ),
            data_quality_notes=list(_LIMITATIONS),
            created_at=self._clock.now(),
        )
        await self._repository.save_report(report)
        run = await self._transition(run, AgentRunStatus.COMPLETED, AgentRunStage.REPORT)
        return AgentRunResult(
            run_id=run.run_id,
            status=run.status,
            snapshot_ids=[snapshot.snapshot_id],
            report_id=report.report_id,
            completed_at=run.completed_at,
        )

    async def _transition(
        self, run: AgentRun, status: AgentRunStatus, stage: AgentRunStage
    ) -> AgentRun:
        require_transition(run.status, status, RUN_TRANSITIONS)
        now = self._clock.now()
        updated = run.model_copy(
            update={
                "status": status,
                "current_stage": stage,
                "updated_at": now,
                "completed_at": now if status is AgentRunStatus.COMPLETED else None,
            }
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
                summary=f"Saved collection run moved to {status.value}",
                details={"stage": stage.value, "external_reads": 0},
            )
        )
        return updated

    async def finalize_after_actions(self, run_id: str) -> AgentRunResult:
        raise ValueError("Saved collection reports create no actions to finalize")
