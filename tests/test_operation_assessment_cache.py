import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import cast

import pytest

from app.mana_operation_ai.application.ports import OperationRepository
from app.mana_operation_ai.application.retention.assessment_cache import (
    RetentionAssessmentCache,
    engagement_assessment_key,
)
from app.mana_operation_ai.application.retention.engagement import (
    RetentionEngagementCapabilityHandler,
    _normalize,
)
from app.mana_operation_ai.application.runtime import UuidGenerator
from app.mana_operation_ai.domain.cost_control import ProductScope
from app.mana_operation_ai.domain.enums import AgentRunStatus, TriggerType
from app.mana_operation_ai.domain.models import AgentRun, Analysis, Finding
from app.mana_operation_ai.domain.retention import (
    EngagementAssessment,
    RetentionEngagementConfiguration,
    RetentionEngagementSnapshot,
)
from app.mana_operation_ai.infrastructure.persistence.assessment_store import (
    SqlAlchemyEngagementAssessmentStore,
)
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.retention.fake import (
    FakeBackendActivityAdapter,
    FakeMobileActivityAdapter,
)
from tests.test_operation_cost_ledger import Clock

Scenario = tuple[
    OperationDatabase, Clock, RetentionEngagementSnapshot, RetentionEngagementCapabilityHandler
]


@pytest.fixture
async def scenario(tmp_path: Path) -> AsyncIterator[Scenario]:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'assessment.db'}")
    await db.create_schema()
    clock = Clock(datetime(2026, 10, 8, 12, tzinfo=UTC))
    backend = FakeBackendActivityAdapter(clock=clock)
    mobile = FakeMobileActivityAdapter(clock=clock)
    start = clock.now() - timedelta(days=7)
    facts = await backend.collect_activity(period_start=start, period_end=clock.now())
    events = await mobile.collect_activity(period_start=start, period_end=clock.now())
    approved = {
        "product_scope": ProductScope.MANA,
        "fresh_until": clock.now() + timedelta(hours=6),
    }
    snapshot = _normalize(
        facts.model_copy(update=approved), events.model_copy(update=approved), None, clock.now()
    )
    handler = RetentionEngagementCapabilityHandler(
        backend_activity=backend,
        mobile_activity=mobile,
        operational_telemetry=None,
        repository=cast(OperationRepository, object()),
        clock=clock,
        ids=UuidGenerator(),
    )
    try:
        yield db, clock, snapshot, handler
    finally:
        await db.dispose()


def calculation(
    handler: RetentionEngagementCapabilityHandler,
    snapshot: RetentionEngagementSnapshot,
    configuration: RetentionEngagementConfiguration,
    clock: Clock,
) -> tuple[Analysis, list[Finding]]:
    run = AgentRun(
        run_id="fixture-run",
        agent_id="retention-agent",
        capability_key="retention.engagement.analyze",
        correlation_id="fixture-correlation",
        trigger=TriggerType.USER,
        initiated_by="fixture-operator",
        status=AgentRunStatus.ANALYZING,
        configuration_version=1,
        idempotency_key="fixture",
        started_at=clock.now(),
        updated_at=clock.now(),
    )
    return handler._analyze(
        run=run,
        snapshot=handler._snapshot(run, snapshot, []),
        normalized=snapshot,
        configuration=configuration,
    )


@pytest.mark.asyncio
async def test_assessment_reuse_matches_real_rules_after_restart(scenario: Scenario) -> None:
    db, clock, snapshot, handler = scenario
    config = RetentionEngagementConfiguration(product=ProductScope.MANA)
    calculated = 0

    def calculate() -> tuple[Analysis, list[Finding]]:
        nonlocal calculated
        calculated += 1
        return calculation(handler, snapshot, config, clock)

    first, findings, reused = await RetentionAssessmentCache(
        SqlAlchemyEngagementAssessmentStore(db), clock=clock
    ).assess(snapshot=snapshot, configuration=config, configuration_version=1, calculate=calculate)
    assert not reused and calculated == 1
    clock.value += timedelta(hours=1)
    cached = snapshot.model_copy(
        update={
            "refresh_status": "cached",
            "evidence_refs": [
                reference.model_copy(update={"freshness_seconds": 3600})
                for reference in snapshot.evidence_refs
            ],
        }
    )
    reopened = OperationDatabase(str(db.engine.url))
    try:
        second, same_findings, reused = await RetentionAssessmentCache(
            SqlAlchemyEngagementAssessmentStore(reopened), clock=clock
        ).assess(
            snapshot=cached, configuration=config, configuration_version=1, calculate=calculate
        )
        assert reused and calculated == 1
        assert second == first and same_findings == findings
        assert second.calculated_at == datetime(2026, 10, 8, 12, tzinfo=UTC)
        expected, expected_findings = calculation(handler, snapshot, config, clock)
        assert second.metrics == expected.metrics
        assert second.data_quality_score == expected.data_quality_score
        assert [(item.finding_type, item.evidence) for item in findings] == [
            (item.finding_type, item.evidence) for item in expected_findings
        ]
    finally:
        await reopened.dispose()


@pytest.mark.asyncio
async def test_changed_configuration_data_and_version_require_new_assessment(
    scenario: Scenario,
) -> None:
    db, clock, snapshot, handler = scenario
    cache = RetentionAssessmentCache(SqlAlchemyEngagementAssessmentStore(db), clock=clock)
    config = RetentionEngagementConfiguration(product=ProductScope.MANA)
    changed = config.model_copy(update={"minimum_active_child_ratio": Decimal("0.9")})
    for current, current_config, version in (
        (snapshot, config, 1),
        (snapshot, changed, 1),
        (snapshot, changed, 2),
        (snapshot.model_copy(update={"backend_active_children": 1}), changed, 2),
        (snapshot.model_copy(update={"limitations": ["New source limitation"]}), config, 1),
    ):
        result, findings, reused = await cache.assess(
            snapshot=current,
            configuration=current_config,
            configuration_version=version,
            calculate=partial(calculation, handler, current, current_config, clock),
        )
        assert not reused
        if current_config.minimum_active_child_ratio == Decimal("0.9"):
            assert any(item.finding_type == "low_backend_engagement" for item in findings)
        assert result.calculated_at == clock.now()
    original = engagement_assessment_key(snapshot, config, 1)
    assert original != engagement_assessment_key(snapshot, config, 1, rules_version="next-rules")
    assert original != engagement_assessment_key(
        snapshot.model_copy(update={"product_scope": ProductScope.REC360}),
        config.model_copy(update={"product": ProductScope.REC360}),
        1,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["expired", "stale", "unverified", "wrong_product", "future"])
async def test_time_and_scope_conditions_prevent_assessment_reuse(
    scenario: Scenario, condition: str
) -> None:
    db, clock, snapshot, handler = scenario
    cache = RetentionAssessmentCache(SqlAlchemyEngagementAssessmentStore(db), clock=clock)
    config = RetentionEngagementConfiguration(product=ProductScope.MANA)

    def calculate() -> tuple[Analysis, list[Finding]]:
        return calculation(handler, snapshot, config, clock)

    await cache.assess(
        snapshot=snapshot, configuration=config, configuration_version=1, calculate=calculate
    )
    match condition:
        case "expired":
            clock.value += timedelta(hours=6)
        case "stale":
            snapshot = snapshot.model_copy(update={"refresh_status": "stale"})
        case "unverified":
            snapshot = snapshot.model_copy(update={"product_scope": ProductScope.UNVERIFIED})
        case "wrong_product":
            config = config.model_copy(update={"product": ProductScope.REC360})
        case "future":
            clock.value -= timedelta(seconds=1)
    _, _, reused = await cache.assess(
        snapshot=snapshot, configuration=config, configuration_version=1, calculate=calculate
    )
    assert not reused


@pytest.mark.asyncio
async def test_concurrent_deterministic_publish_cannot_extend_validity_or_cross_apps(
    scenario: Scenario,
) -> None:
    db, clock, snapshot, handler = scenario
    config = RetentionEngagementConfiguration(product=ProductScope.MANA)
    assert snapshot.fresh_until is not None
    analysis, findings = calculation(handler, snapshot, config, clock)
    result = EngagementAssessment(
        product=ProductScope.MANA,
        valid_until=snapshot.fresh_until,
        analysis=analysis,
        findings=findings,
    )
    store = SqlAlchemyEngagementAssessmentStore(db)
    key = engagement_assessment_key(snapshot, config, 1)
    await store.put(key, result)
    later = result.model_copy(update={"valid_until": result.valid_until + timedelta(days=1)})
    await asyncio.gather(*[store.put(key, later) for _ in range(12)])
    saved = await store.get(key, product=ProductScope.MANA, now=clock.now())
    assert saved == result
    assert await store.get(key, product=ProductScope.REC360, now=clock.now()) is None
    assert await store.get(key, product=ProductScope.MANA, now=result.valid_until) is None
