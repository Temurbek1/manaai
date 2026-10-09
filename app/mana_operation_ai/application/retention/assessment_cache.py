import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from app.mana_operation_ai.application.ports import Clock
from app.mana_operation_ai.domain.cost_control import ProductScope
from app.mana_operation_ai.domain.models import Analysis, Finding
from app.mana_operation_ai.domain.retention import (
    EngagementAssessment,
    RetentionEngagementConfiguration,
    RetentionEngagementSnapshot,
)


class EngagementAssessmentStore(Protocol):
    async def get(
        self, key: str, *, product: ProductScope, now: datetime
    ) -> EngagementAssessment | None: ...

    async def put(self, key: str, result: EngagementAssessment) -> None: ...


class RetentionAssessmentCache:
    """Memoize the existing pure aggregate assessment, never a conversation/action.

    Its entire task is the typed engagement configuration. It has no free-text
    goals, user-specific evidence, provider/model calls or mutable target state.
    Future task inputs or rule changes must revise this explicit identity.
    """

    def __init__(self, store: EngagementAssessmentStore, *, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    async def assess(
        self,
        *,
        snapshot: RetentionEngagementSnapshot,
        configuration: RetentionEngagementConfiguration,
        configuration_version: int,
        calculate: Callable[[], tuple[Analysis, list[Finding]]],
    ) -> tuple[Analysis, list[Finding], bool]:
        now = self._clock.now()
        expiry = snapshot.fresh_until
        eligible = (
            snapshot.product_scope is not ProductScope.UNVERIFIED
            and configuration.product is snapshot.product_scope
            and snapshot.refresh_status in {"live", "cached"}
            and now.utcoffset() is not None
            and snapshot.collected_at.utcoffset() is not None
            and snapshot.collected_at <= now
            and expiry is not None
            and expiry.utcoffset() is not None
            and snapshot.collected_at < expiry
            and now < expiry
        )
        if not eligible or expiry is None:
            analysis, findings = calculate()
            return analysis, findings, False
        key = engagement_assessment_key(snapshot, configuration, configuration_version)
        saved = await self._store.get(key, product=snapshot.product_scope, now=now)
        # Also validate payload metadata; a DB row alone is not evidence.
        if (
            saved is not None
            and saved.product is snapshot.product_scope
            and saved.valid_until == expiry
            and saved.analysis.calculated_at.utcoffset() is not None
            and saved.analysis.calculated_at <= now
        ):
            return saved.analysis, saved.findings, True
        analysis, findings = calculate()
        await self._store.put(
            key,
            EngagementAssessment(
                product=snapshot.product_scope,
                valid_until=expiry,
                analysis=analysis,
                findings=findings,
            ),
        )
        return analysis, findings, False


def engagement_assessment_key(
    snapshot: RetentionEngagementSnapshot,
    configuration: RetentionEngagementConfiguration,
    configuration_version: int,
    *,
    rules_version: str = "retention-engagement-assessment-v1",
) -> str:
    facts = snapshot.model_dump(mode="json", exclude={"refresh_status"})
    # Age/status describe delivery, not changed observations. Eligibility and the
    # exact original expiry are checked independently on every reuse.
    for reference in facts["evidence_refs"]:
        reference.pop("freshness_seconds", None)
    operational = facts.get("operational_telemetry")
    if operational is not None:
        operational.pop("refresh_status", None)
    canonical = json.dumps(
        {
            "task": "retention.engagement.analyze",
            "rules_version": rules_version,
            "configuration_version": configuration_version,
            "configuration": configuration.model_dump(mode="json"),
            "facts": facts,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
