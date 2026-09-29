from app.mana_operation_ai.application.ports import Clock, OperationRepository
from app.mana_operation_ai.application.retention.constants import (
    ENGAGEMENT_CAPABILITY_KEY,
    RETENTION_AGENT_ID,
)
from app.mana_operation_ai.domain.enums import AgentRunStatus
from app.mana_operation_ai.domain.retention import RetentionEngagementSnapshot, RetentionOverview


class RetentionOverviewService:
    """Build an administrator view exclusively from persisted, scoped evidence."""

    def __init__(self, repository: OperationRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    async def overview(self) -> RetentionOverview:
        runs, _ = await self._repository.list_runs(
            agent_id=RETENTION_AGENT_ID,
            capability_key=ENGAGEMENT_CAPABILITY_KEY,
            limit=20,
        )
        completed, _ = await self._repository.list_runs(
            agent_id=RETENTION_AGENT_ID,
            capability_key=ENGAGEMENT_CAPABILITY_KEY,
            status=AgentRunStatus.COMPLETED,
            limit=1,
        )
        reports, _ = await self._repository.list_reports(
            agent_id=RETENTION_AGENT_ID,
            capability_key=ENGAGEMENT_CAPABILITY_KEY,
            limit=10,
        )
        result = RetentionOverview(
            generated_at=self._clock.now(),
            mode="unavailable",
            latest_run=runs[0] if runs else None,
            recent_runs=runs,
            reports=reports,
        )
        if not completed:
            return result
        run = completed[0]
        snapshots = await self._repository.list_snapshots(run.run_id)
        eligible = [
            item
            for item in snapshots
            if item.agent_id == RETENTION_AGENT_ID
            and item.capability_key == ENGAGEMENT_CAPABILITY_KEY
            and item.schema_version == "retention-engagement-v2"
        ]
        if not eligible:
            return result
        stored = max(eligible, key=lambda item: item.collected_at)
        snapshot = RetentionEngagementSnapshot.model_validate(stored.payload)
        findings, _ = await self._repository.list_findings(run_id=run.run_id, limit=100)
        sources = {
            item.source for item in snapshot.evidence_refs if "unconfigured" not in item.source
        }
        fake = {item for item in sources if item.startswith("fake_")}
        mode = "mixed" if fake and sources - fake else "demo" if fake else "live"
        return result.model_copy(
            update={
                "mode": mode if sources else "unavailable",
                "snapshot_run_id": run.run_id,
                "snapshot": snapshot,
                "snapshot_age_seconds": max(
                    int((self._clock.now() - snapshot.collected_at).total_seconds()),
                    0,
                ),
                "mobile_analytics_available": any(
                    item.source
                    in {"google_analytics_4", "firebase_app_activity", "fake_firestore_activity"}
                    and item.completeness > 0
                    for item in snapshot.evidence_refs
                ),
                "findings": findings,
            },
        )
